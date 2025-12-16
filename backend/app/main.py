import logging
from uuid import uuid4
from typing import List

from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.middleware.cors import CORSMiddleware

from .logging_config import setup_logging
from .models.schemas import (
    ChatRequest,
    ChatResponse,
    TIRScoreRequest,
    TIRScoreResponse,
    TIRSingleResult,
    SaveEditedRequest,
)
from .rag.chat_rag import build_fdsc_chat_runnable
from .rag.tir_scoring import score_tir_dataset
from .services.storage_service import (
    upload_result_markdown,
    load_structured_results,
    update_markdown_in_results,
)
from .services.export_service import build_docx_from_results, build_pdf_from_results

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="FDSC RAG & TIR Scoring App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthcheck():
    return {"status": "ok"}


@app.post("/api/chat/message", response_model=ChatResponse)
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


@app.post("/api/tir/score", response_model=TIRScoreResponse)
async def tir_score(req: TIRScoreRequest):
    try:
        session_id = req.session_id or str(uuid4())
        raw_results = score_tir_dataset(session_id, req.fdsc_index_name, req.dataset_prefix)

        results: List[TIRSingleResult] = []
        for r in raw_results:
            results.append(
                TIRSingleResult(
                    tir_blob_path=r["tir_blob_path"],
                    rationale=r["rationale"],
                    markdown_table=r["markdown_table"],
                    raw_structured=r,
                    technical_review=r["technical_review"],
                    alignment_review=r["alignment_review"],
                )
            )

        return TIRScoreResponse(session_id=session_id, results=results)
    except Exception as ex:
        logger.exception("Error in /api/tir/score")
        raise HTTPException(status_code=500, detail="Scoring failed") from ex


@app.post("/api/tir/save")
async def save_edited_markdown(req: SaveEditedRequest):
    try:
        decoded_tir_id = req.tir_id
        try:
            from urllib.parse import unquote

            decoded_tir_id = unquote(req.tir_id)
        except Exception:
            logger.warning("Failed to decode tir_id %s, using raw value", req.tir_id)

        blob_name = f"{req.session_id}/{decoded_tir_id}.md"
        upload_result_markdown(blob_name, req.edited_markdown)

        updated = update_markdown_in_results(req.session_id, decoded_tir_id, req.edited_markdown)

        return {"status": "ok", "blob_name": blob_name, "structured_updated": updated}
    except Exception as ex:
        logger.exception("Error in /api/tir/save")
        raise HTTPException(status_code=500, detail="Save failed") from ex


@app.get("/api/tir/export/docx")
async def export_docx(session_id: str = Query(...)):
    try:
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


@app.get("/api/tir/export/pdf")
async def export_pdf(session_id: str = Query(...)):
    try:
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
