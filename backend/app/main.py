import logging
import re
from uuid import uuid4
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Response, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

from .logging_config import setup_logging
from .config import get_settings
from .models.schemas import (
    ChatRequest,
    ChatResponse,
    FDSCDocument,
    TIRScoreRequest,
    TIRScoreResponse,
    TIRSingleResult,
    SaveEditedRequest,
)
from .errors import AppError
from .rag.chat_rag import build_fdsc_chat_runnable
from .rag.tir_scoring import score_tir_dataset
from .services.storage_service import (
    upload_result_markdown,
    load_structured_results,
    update_markdown_in_results,
    list_tir_prefixes,
    list_fdsc_document_metadata,
    list_fdsc_prefixes,
    get_fdsc_document_metadata,
    list_tir_files,
)
from .services.export_service import build_docx_from_results, build_pdf_from_results
from .utils.rate_limit import enforce_rate_limit
from .utils.session_tokens import issue_session_token, verify_session_token
from .pipelines.fdsc_ingestion import ingest_fdsc_document

setup_logging()
settings = get_settings()
logger = logging.getLogger(__name__)
_ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
_TIR_SAVE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9/._ -]{1,256}$")
_ALLOWED_UPLOAD_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/octet-stream",
}

app = FastAPI(title="FDSC RAG & TIR Scoring App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for prod
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthcheck():
    return {"status": "ok"}


@app.post(
    "/api/chat/message",
    response_model=ChatResponse,
    dependencies=[Depends(enforce_rate_limit)],
)
async def chat_message(req: ChatRequest):
    try:
        chat_runnable = build_fdsc_chat_runnable(req.fdsc_index_name)
        result = chat_runnable.invoke(
            {"question": req.message},
            config={"configurable": {"session_id": req.session_id}},
        )

        answer_msg = result["answer"]
        docs = result.get("source_documents", [])

        citations = []
        for d in docs:
            citations.append(
                {
                    "source_id": d.metadata.get("id"),
                    "page": d.metadata.get("page"),
                    "blob_uri": d.metadata.get("blob_uri"),
                    "snippet": d.page_content[:200],
                }
            )

        return ChatResponse(answer=answer_msg.content, citations=citations)
    except Exception as ex:
        logger.exception("Error in /api/chat/message")
        raise HTTPException(status_code=500, detail="Chat failed") from ex


@app.post(
    "/api/tir/score",
    response_model=TIRScoreResponse,
    dependencies=[Depends(enforce_rate_limit)],
)
async def tir_score(req: TIRScoreRequest):
    try:
        session_id = _resolve_or_create_scoring_session(req)
        _validate_score_request(req)
        raw_results = score_tir_dataset(
            session_id,
            req.fdsc_index_name,
            req.dataset_prefix,
            req.fdsc_doc_id,
            req.tir_blob_path,
        )
        if not raw_results:
            raise AppError(
                "No TIR files were found for the selected filters. Confirm the dataset prefix and selected TIR.",
                status_code=404,
                code="tir_not_found",
                details={"dataset_prefix": req.dataset_prefix, "tir_blob_path": req.tir_blob_path},
            )

        results: List[TIRSingleResult] = []
        for r in raw_results:
            results.append(
                TIRSingleResult(
                    tir_id=r["tir_id"],
                    dataset_prefix=r["dataset_prefix"],
                    tir_blob_path=r["tir_blob_path"],
                    rationale=r["rationale"],
                    markdown_table=r["markdown_table"],
                    raw_structured=r,
                    technical_review=r["technical_review"],
                    alignment_review=r["alignment_review"],
                )
            )

        return TIRScoreResponse(
            session_id=session_id,
            session_token=issue_session_token(session_id),
            results=results,
        )
    except AppError as ex:
        logger.exception("Validation error in /api/tir/score")
        raise HTTPException(status_code=ex.status_code, detail=ex.to_detail()) from ex
    except Exception as ex:
        logger.exception("Error in /api/tir/score")
        raise HTTPException(
            status_code=500,
            detail={"message": "Scoring failed due to an internal error.", "code": "scoring_failed"},
        ) from ex


@app.post("/api/tir/save", dependencies=[Depends(enforce_rate_limit)])
async def save_edited_markdown(req: SaveEditedRequest):
    try:
        _assert_scoring_session(req.session_id, req.session_token)
        decoded_tir_id = req.tir_id
        try:
            from urllib.parse import unquote

            decoded_tir_id = unquote(req.tir_id)
        except Exception:
            logger.warning("Failed to decode tir_id %s, using raw value", req.tir_id)

        decoded_tir_id = _normalize_tir_save_path(decoded_tir_id)
        existing_results = load_structured_results(req.session_id)
        in_session = any(item.get("tir_blob_path") == decoded_tir_id for item in existing_results)
        if not in_session:
            raise AppError(
                "The selected TIR is not part of the current session results. Re-run scoring and try again.",
                status_code=404,
                code="tir_not_in_session",
                details={"session_id": req.session_id, "tir_blob_path": decoded_tir_id},
            )

        blob_name = f"{req.session_id}/{decoded_tir_id}.md"
        upload_result_markdown(blob_name, req.edited_markdown)

        updated = update_markdown_in_results(req.session_id, decoded_tir_id, req.edited_markdown)
        if not updated:
            raise AppError(
                "The selected TIR is not part of the current session results. Re-run scoring and try again.",
                status_code=404,
                code="tir_not_in_session",
                details={"session_id": req.session_id, "tir_blob_path": decoded_tir_id},
            )

        return {"status": "ok", "blob_name": blob_name, "structured_updated": updated}
    except AppError as ex:
        logger.exception("Validation error in /api/tir/save")
        raise HTTPException(status_code=ex.status_code, detail=ex.to_detail()) from ex
    except Exception as ex:
        logger.exception("Error in /api/tir/save")
        raise HTTPException(
            status_code=500,
            detail={"message": "Save failed due to an internal error.", "code": "save_failed"},
        ) from ex


@app.get("/api/tir/export/docx", dependencies=[Depends(enforce_rate_limit)])
async def export_docx(session_id: str = Query(...), session_token: str = Query(...)):
    try:
        _assert_scoring_session(session_id, session_token)
        results = load_structured_results(session_id)
        if not results:
            raise HTTPException(status_code=404, detail="No TIR results found for this session")
        data = build_docx_from_results(results)
        return Response(
            content=data,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            headers={"Content-Disposition": f'attachment; filename="TIR_Scores_{session_id}.docx"'},
        )
    except Exception as ex:
        logger.exception("Error in /api/tir/export/docx")
        raise HTTPException(status_code=500, detail="Export DOCX failed") from ex


@app.get("/api/tir/export/pdf", dependencies=[Depends(enforce_rate_limit)])
async def export_pdf(session_id: str = Query(...), session_token: str = Query(...)):
    try:
        _assert_scoring_session(session_id, session_token)
        results = load_structured_results(session_id)
        if not results:
            raise HTTPException(status_code=404, detail="No TIR results found for this session")
        data = build_pdf_from_results(results)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="TIR_Scores_{session_id}.pdf"'},
        )
    except Exception as ex:
        logger.exception("Error in /api/tir/export/pdf")
        raise HTTPException(status_code=500, detail="Export PDF failed") from ex


@app.get("/api/tir/prefixes", dependencies=[Depends(enforce_rate_limit)])
async def list_tir_dataset_prefixes():
    try:
        prefixes = list_tir_prefixes()
        return {"prefixes": prefixes}
    except Exception as ex:  # pylint: disable=broad-except
        logger.exception("Error listing dataset prefixes")
        raise HTTPException(status_code=500, detail="Failed to list dataset prefixes") from ex


@app.get("/api/fdsc/docs", dependencies=[Depends(enforce_rate_limit)])
async def list_fdsc_docs(fdsc_index_name: str = Query(...)):
    try:
        documents = list_fdsc_document_metadata(fdsc_index_name)
        typed_documents = []
        for doc in documents:
            try:
                typed_documents.append(FDSCDocument.model_validate(doc).model_dump())
            except Exception:  # pylint: disable=broad-except
                logger.exception("Skipping invalid FDSC metadata row for doc_id=%s", doc.get("doc_id"))
        return {"documents": typed_documents}
    except Exception as ex:  # pylint: disable=broad-except
        logger.exception("Error listing FDSC documents")
        raise HTTPException(status_code=500, detail="Failed to list FDSC documents") from ex


@app.get("/api/fdsc/prefixes", dependencies=[Depends(enforce_rate_limit)])
async def list_fdsc_doc_prefixes(fdsc_index_name: str = Query(...)):
    try:
        prefixes = list_fdsc_prefixes(fdsc_index_name)
        return {"prefixes": prefixes}
    except Exception as ex:  # pylint: disable=broad-except
        logger.exception("Error listing FDSC prefixes")
        raise HTTPException(status_code=500, detail="Failed to list FDSC prefixes") from ex


@app.post("/api/fdsc/upload", dependencies=[Depends(enforce_rate_limit)])
async def upload_fdsc_document(
    fdsc_index_name: str = Form(...),
    doc_id: str = Form(...),
    doc_namespace: str | None = Form(None),
    use_semantic_chunking: bool | None = Form(None),
    file: UploadFile = File(...),
):
    try:
        _validate_upload_file(file)
        payload = await file.read()
        if len(payload) > settings.FDSC_UPLOAD_MAX_BYTES:
            raise AppError(
                f"File is too large. Max allowed size is {settings.FDSC_UPLOAD_MAX_BYTES} bytes.",
                status_code=413,
                code="file_too_large",
                details={"max_bytes": settings.FDSC_UPLOAD_MAX_BYTES},
            )
        if not payload:
            raise AppError(
                "Uploaded file is empty.",
                status_code=400,
                code="empty_file",
            )

        metadata = ingest_fdsc_document(
            fdsc_index_name=fdsc_index_name,
            doc_id=doc_id,
            namespace=doc_namespace or settings.FDSC_DEFAULT_NAMESPACE,
            filename=file.filename or "uploaded",
            data=payload,
            content_type=file.content_type,
            use_semantic_chunking=use_semantic_chunking,
        )
        return {"status": "ok", "document": metadata}
    except AppError as ex:
        logger.exception("Validation error in /api/fdsc/upload")
        raise HTTPException(status_code=ex.status_code, detail=ex.to_detail()) from ex
    except HTTPException:
        raise
    except ValueError as ex:
        logger.exception("Invalid upload request")
        raise HTTPException(
            status_code=400,
            detail={"message": str(ex), "code": "invalid_upload"},
        ) from ex
    except RuntimeError as ex:
        logger.exception("Indexing not ready after upload")
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(ex),
                "code": "indexing_in_progress",
                "details": {
                    "hint": "Wait for ingestion status to become 'indexed' in FDSC Document Manager, then retry."
                },
            },
        ) from ex
    except Exception as ex:  # pylint: disable=broad-except
        logger.exception("Error uploading FDSC doc")
        raise HTTPException(
            status_code=500,
            detail={"message": "Failed to ingest FDSC document", "code": "ingestion_failed"},
        ) from ex


def _validate_upload_file(file: UploadFile) -> None:
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise AppError(
            "Unsupported file type. Allowed extensions: .pdf, .docx, .txt, .md",
            status_code=400,
            code="unsupported_file_type",
            details={"filename": filename},
        )
    content_type = file.content_type or "application/octet-stream"
    if content_type not in _ALLOWED_UPLOAD_CONTENT_TYPES:
        raise AppError(
            f"Unsupported content type '{content_type}'.",
            status_code=400,
            code="unsupported_content_type",
            details={"content_type": content_type},
        )


def _validate_score_request(req: TIRScoreRequest) -> None:
    available_prefixes = {entry["value"] for entry in list_tir_prefixes()}
    if req.dataset_prefix not in available_prefixes:
        raise AppError(
            "Selected TIR dataset prefix does not exist. Refresh the dataset list and choose a valid prefix.",
            status_code=400,
            code="dataset_prefix_not_found",
            details={"dataset_prefix": req.dataset_prefix},
        )

    tir_files = list_tir_files(req.dataset_prefix)
    if not tir_files:
        raise AppError(
            "Selected dataset prefix exists but has no TIR files.",
            status_code=400,
            code="dataset_empty",
            details={"dataset_prefix": req.dataset_prefix},
        )

    if req.tir_blob_path and req.tir_blob_path not in set(tir_files):
        raise AppError(
            "Selected TIR file was not found under the dataset prefix.",
            status_code=400,
            code="tir_not_found",
            details={"tir_blob_path": req.tir_blob_path, "dataset_prefix": req.dataset_prefix},
        )

    if req.fdsc_doc_id:
        known_docs = {entry["value"] for entry in list_fdsc_prefixes(index_name=req.fdsc_index_name)}
        if req.fdsc_doc_id not in known_docs:
            raise AppError(
                "Selected FDSC document prefix does not exist for the chosen index.",
                status_code=400,
                code="fdsc_prefix_not_found",
                details={"fdsc_doc_id": req.fdsc_doc_id, "fdsc_index_name": req.fdsc_index_name},
            )
        metadata = get_fdsc_document_metadata(req.fdsc_index_name, req.fdsc_doc_id)
        if not metadata:
            raise AppError(
                "Selected FDSC document metadata was not found.",
                status_code=404,
                code="fdsc_doc_not_found",
                details={"fdsc_doc_id": req.fdsc_doc_id, "fdsc_index_name": req.fdsc_index_name},
            )
        status = str(metadata.get("ingestion_status", "indexed"))
        if status != "indexed":
            raise AppError(
                "Selected FDSC document is still ingesting. Wait until status is 'indexed' before scoring.",
                status_code=409,
                code="fdsc_not_indexed",
                details={"fdsc_doc_id": req.fdsc_doc_id, "ingestion_status": status},
            )


def _normalize_tir_save_path(value: str) -> str:
    cleaned = value.strip("/")
    segments = cleaned.split("/")
    if not cleaned or any(seg in {"", ".", ".."} for seg in segments):
        raise AppError(
            "Invalid TIR identifier.",
            status_code=400,
            code="invalid_tir_id",
        )
    if not _TIR_SAVE_PATH_PATTERN.fullmatch(cleaned):
        raise AppError(
            "Invalid characters in TIR identifier.",
            status_code=400,
            code="invalid_tir_id",
        )
    return cleaned


def _resolve_or_create_scoring_session(req: TIRScoreRequest) -> str:
    if not req.session_id:
        return str(uuid4())
    if not req.session_token:
        raise AppError(
            "Missing session token for existing session. Start a new scoring run or refresh the page.",
            status_code=401,
            code="missing_session_token",
        )
    _assert_scoring_session(req.session_id, req.session_token)
    return req.session_id


def _assert_scoring_session(session_id: str, session_token: str) -> None:
    if not verify_session_token(session_id, session_token):
        raise AppError(
            "Session is invalid or expired. Re-run scoring to start a new session.",
            status_code=401,
            code="invalid_session",
        )
