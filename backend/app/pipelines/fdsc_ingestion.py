import io
import hashlib
import logging
import re
import time
from datetime import datetime
from typing import List, Optional

import fitz
from docx import Document
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

from ..azure_clients import doc_intel_client, embeddings, get_search_client
from ..config import get_settings
from ..services.storage_service import (
    save_fdsc_source_document,
    upsert_fdsc_document_metadata,
    invalidate_fdsc_prefix_cache,
)
from ..utils.backoff_utils import azure_retry

logger = logging.getLogger(__name__)
settings = get_settings()
_DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _preprocess_text(text: str) -> str:
    cleaned = re.sub(r"\r\n", "\n", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_text(filename: str, content_type: Optional[str], data: bytes) -> str:
    lower_name = (filename or "").lower()
    if lower_name.endswith(".pdf") or content_type == "application/pdf":
        doc = fitz.open(stream=data, filetype="pdf")
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(pages)
    if lower_name.endswith(".docx") or content_type in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}:
        document = Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="ignore")


class BaseChunker:
    def chunk(self, text: str) -> List[str]:
        raise NotImplementedError


class FixedWindowChunker(BaseChunker):
    def __init__(self, chunk_size: int, overlap: int):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> List[str]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0
        for para in paragraphs:
            para_len = len(para)
            if current and current_len + para_len > self.chunk_size:
                chunks.append("\n\n".join(current))
                overlap_text = ""
                if self.overlap and chunks[-1]:
                    overlap_text = chunks[-1][-self.overlap :]
                current = [overlap_text.strip(), para] if overlap_text else [para]
                current_len = sum(len(item) for item in current)
            else:
                current.append(para)
                current_len += para_len
        if current:
            chunks.append("\n\n".join([c for c in current if c]))
        return [c for c in chunks if c]


class SemanticChunker(BaseChunker):
    """
    Lightweight semantic chunker that respects headings and sections before
    falling back to length-based splitting.
    """

    def __init__(self, max_chars: int, min_chars: int, heading_pattern: str):
        self.max_chars = max_chars
        self.min_chars = min_chars
        self.heading_pattern = re.compile(heading_pattern)

    def chunk(self, text: str) -> List[str]:
        lines = [line.strip() for line in text.splitlines()]
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        def flush():
            nonlocal current, current_len
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0

        for line in lines:
            if not line:
                continue
            if (self.heading_pattern.match(line) or line.endswith(":")) and current_len >= self.min_chars:
                flush()
                current.append(line)
                current_len = len(line)
                continue

            current.append(line)
            current_len += len(line)
            if current_len >= self.max_chars:
                flush()

        flush()

        if not chunks:
            return [text]

        merged: List[str] = []
        buffer = ""
        for chunk in chunks:
            if len(buffer) + len(chunk) < self.min_chars:
                buffer = f"{buffer}\n{chunk}".strip()
                continue
            if buffer:
                merged.append(buffer)
                buffer = ""
            merged.append(chunk)
        if buffer:
            merged.append(buffer)
        return [c for c in merged if c]


def _select_chunker(use_semantic: Optional[bool]) -> BaseChunker:
    if use_semantic is None:
        use_semantic = settings.ENABLE_SEMANTIC_CHUNKING
    if use_semantic:
        return SemanticChunker(
            max_chars=settings.FDSC_SEMANTIC_MAX_CHARS,
            min_chars=settings.FDSC_SEMANTIC_MIN_CHARS,
            heading_pattern=settings.FDSC_SEMANTIC_HEADING_PATTERN,
        )
    return FixedWindowChunker(
        chunk_size=settings.FDSC_FIXED_CHUNK_SIZE,
        overlap=settings.FDSC_FIXED_CHUNK_OVERLAP,
    )


def _delete_existing_chunks(index_name: str, doc_id: str) -> None:
    client = get_search_client(index_name)
    escaped = doc_id.replace("'", "''")
    results = _search_ids_with_retry(client, escaped)
    ids = [doc["id"] for doc in results]
    if ids:
        _delete_documents_with_retry(client, ids)
        logger.info("Deleted %d existing chunks for doc %s", len(ids), doc_id)


def _extract_with_document_intelligence(data: bytes) -> List[str]:
    try:
        request = AnalyzeDocumentRequest(bytes_source=data)
        poller = _begin_analyze_with_retry(request)
        result = _poll_analysis_with_retry(poller)
    except Exception:  # pylint: disable=broad-except
        logger.exception("Azure Document Intelligence analysis failed")
        return []

    paragraphs: List[str] = []
    for para in getattr(result, "paragraphs", []) or []:
        content = getattr(para, "content", "")
        if content:
            paragraphs.append(content.strip())

    if not paragraphs:
        content = getattr(result, "content", None)
        if content:
            paragraphs.append(content.strip())

    return [p for p in paragraphs if p]


@azure_retry
def _begin_analyze_with_retry(request: AnalyzeDocumentRequest):
    return doc_intel_client.begin_analyze_document(
        model_id=settings.AZURE_DOC_INTEL_MODEL_ID,
        analyze_document_request=request,
    )


@azure_retry
def _poll_analysis_with_retry(poller):
    return poller.result()


@azure_retry
def _embed_documents_with_retry(chunks: List[str]) -> List[List[float]]:
    return embeddings.embed_documents(chunks)


@azure_retry
def _upload_documents_with_retry(search_client, documents: List[dict]):
    return search_client.upload_documents(documents=documents)


@azure_retry
def _search_ids_with_retry(search_client, escaped_doc_id: str):
    return list(
        search_client.search(
            search_text="*",
            filter=f"doc_id eq '{escaped_doc_id}'",
            select=["id"],
        )
    )


@azure_retry
def _delete_documents_with_retry(search_client, ids: List[str]) -> None:
    search_client.delete_documents(documents=[{"id": chunk_id} for chunk_id in ids])


@azure_retry
def _count_indexed_chunks(search_client, escaped_doc_id: str) -> int:
    results = search_client.search(
        search_text="*",
        filter=f"doc_id eq '{escaped_doc_id}'",
        top=1,
        include_total_count=True,
        select=["id"],
    )
    return int(results.get_count() or 0)


def _await_document_indexed(fdsc_index_name: str, doc_id: str, timeout_seconds: int) -> int:
    search_client = get_search_client(fdsc_index_name)
    escaped = doc_id.replace("'", "''")
    deadline = time.time() + timeout_seconds
    last_count = 0
    while time.time() < deadline:
        try:
            last_count = _count_indexed_chunks(search_client, escaped)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed checking ingestion status for %s", doc_id)
            last_count = 0
        if last_count > 0:
            return last_count
        time.sleep(2)
    return last_count


def ingest_fdsc_document(
    fdsc_index_name: str,
    doc_id: str,
    filename: str,
    data: bytes,
    namespace: Optional[str] = None,
    content_type: Optional[str] = None,
    use_semantic_chunking: Optional[bool] = None,
) -> dict:
    if not doc_id or not _DOC_ID_PATTERN.fullmatch(doc_id):
        raise ValueError("doc_id contains invalid characters or is empty.")
    namespace = namespace or settings.FDSC_DEFAULT_NAMESPACE
    if not _NAMESPACE_PATTERN.fullmatch(namespace):
        raise ValueError("doc_namespace contains invalid characters.")

    semantic_flag = bool(
        use_semantic_chunking if use_semantic_chunking is not None else settings.ENABLE_SEMANTIC_CHUNKING
    )
    metadata = {
        "doc_id": doc_id,
        "index_name": fdsc_index_name,
        "doc_namespace": namespace,
        "source_file": filename,
        "source_content_sha256": hashlib.sha256(data).hexdigest(),
        "blob_uri": "",
        "chunk_count": 0,
        "semantic_chunking": semantic_flag,
        "used_document_intelligence": False,
        "ingestion_status": "processing",
        "updated_at": datetime.utcnow().isoformat(),
    }

    try:
        upsert_fdsc_document_metadata(metadata)

        di_sections = _extract_with_document_intelligence(data)
        if di_sections:
            combined = "\n\n".join(di_sections)
        else:
            logger.warning("Document Intelligence yielded no content for %s, falling back to local extraction", doc_id)
            combined = _extract_text(filename, content_type, data)

        cleaned = _preprocess_text(combined)
        if not cleaned:
            raise ValueError("Could not extract text from uploaded file.")

        chunker = _select_chunker(use_semantic_chunking)
        chunks = chunker.chunk(cleaned)
        if not chunks:
            raise ValueError("Chunker returned no content for this document.")

        embeddings_values = _embed_documents_with_retry(chunks)
        if len(embeddings_values) != len(chunks):
            raise ValueError("Embedding generation failed for one or more chunks.")

        _delete_existing_chunks(fdsc_index_name, doc_id)

        blob_uri = save_fdsc_source_document(doc_id, filename, data)
        search_client = get_search_client(fdsc_index_name)
        documents = []
        for idx, chunk in enumerate(chunks):
            documents.append(
                {
                    "id": f"{doc_id}::{idx}",
                    "content": chunk,
                    "content_vector": embeddings_values[idx],
                    "page": idx,
                    "blob_uri": blob_uri,
                    "doc_id": doc_id,
                    "doc_namespace": namespace,
                    "chunk_index": idx,
                    "source_file": filename,
                }
            )
        _upload_documents_with_retry(search_client, documents)
        logger.info(
            "Uploaded %d FDSC chunks to index %s for doc %s",
            len(documents),
            fdsc_index_name,
            doc_id,
        )

        indexed_count = _await_document_indexed(
            fdsc_index_name=fdsc_index_name,
            doc_id=doc_id,
            timeout_seconds=settings.FDSC_INGESTION_INDEX_TIMEOUT_SECONDS,
        )
        if indexed_count <= 0:
            raise RuntimeError(
                "Document upload completed but indexing is not ready yet. Please retry scoring in a moment."
            )

        metadata.update(
            {
                "source_file": filename,
                "blob_uri": blob_uri,
                "chunk_count": len(documents),
                "semantic_chunking": semantic_flag,
                "used_document_intelligence": bool(di_sections),
                "ingestion_status": "indexed",
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        upsert_fdsc_document_metadata(metadata)
        invalidate_fdsc_prefix_cache()
        return metadata
    except RuntimeError:
        metadata.update(
            {
                "ingestion_status": "processing",
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        upsert_fdsc_document_metadata(metadata)
        raise
    except Exception:
        metadata.update(
            {
                "ingestion_status": "failed",
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        upsert_fdsc_document_metadata(metadata)
        raise
