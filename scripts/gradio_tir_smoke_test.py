#!/usr/bin/env python3
"""Minimal Gradio harness for FDSC upload + single-TIR scoring smoke tests."""

from __future__ import annotations

import json
import os
import sys
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import gradio as gr
except ModuleNotFoundError as ex:
    raise SystemExit("gradio is required. Install it with: pip install gradio") from ex

from backend.app.pipelines.fdsc_ingestion import ingest_fdsc_document
from backend.app.rag.retriever import get_fdsc_hybrid_retriever
from backend.app.rag.tir_scoring import ScoreSingleTIRConfig, score_single_tir
from backend.app.services.storage_service import (
    download_tir_file_text,
    get_fdsc_document_metadata,
    list_fdsc_document_metadata,
    list_fdsc_prefixes,
    list_tir_files,
    list_tir_prefixes,
)


def _normalize_upload(upload_value: Any) -> Tuple[Optional[bytes], Optional[str]]:
    """Accept bytes/str/list/file-like and normalize to (bytes, filename)."""
    if upload_value is None:
        return None, None

    value = upload_value
    if isinstance(value, list):
        if not value:
            return None, None
        value = value[0]

    if isinstance(value, bytes):
        return value, "uploaded.bin"

    if isinstance(value, str):
        path = Path(value)
        if path.exists() and path.is_file():
            return path.read_bytes(), path.name
        return value.encode("utf-8"), "uploaded.txt"

    if isinstance(value, dict):
        filename = str(value.get("name") or "uploaded.bin")
        data = value.get("data")
        if isinstance(data, bytes):
            return data, Path(filename).name
        if isinstance(data, str):
            data_path = Path(data)
            if data_path.exists() and data_path.is_file():
                return data_path.read_bytes(), data_path.name
            return data.encode("utf-8"), Path(filename).name

    if hasattr(value, "name") and isinstance(getattr(value, "name"), str):
        candidate = Path(getattr(value, "name"))
        if candidate.exists() and candidate.is_file():
            return candidate.read_bytes(), candidate.name

    if hasattr(value, "read"):
        data = value.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        if isinstance(data, bytes):
            filename = Path(getattr(value, "name", "uploaded.bin")).name
            return data, filename

    return None, None


def _content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _list_fdsc_doc_choices(fdsc_index_name: str) -> List[str]:
    if not fdsc_index_name:
        return []
    return [entry["value"] for entry in list_fdsc_prefixes(index_name=fdsc_index_name)]


def _list_tir_prefix_choices() -> List[str]:
    return [entry["value"] for entry in list_tir_prefixes()]


def _list_tir_choices(dataset_prefix: str) -> List[str]:
    if not dataset_prefix:
        return []
    return list_tir_files(dataset_prefix)


def _format_context_docs(docs: List[Any]) -> str:
    if not docs:
        return "No retrieved context documents."

    lines: List[str] = []
    for idx, doc in enumerate(docs[:8], start=1):
        metadata = doc.metadata or {}
        snippet = (doc.page_content or "").strip().replace("\n", " ")
        lines.append(
            f"[{idx}] id={metadata.get('id')} page={metadata.get('page')} doc_id={metadata.get('doc_id')} "
            f"mode={metadata.get('retrieval_mode')}"
        )
        lines.append(f"    snippet: {snippet[:320]}")
    return "\n".join(lines)


def _apply_upload_or_reuse(
    fdsc_file: Any,
    fdsc_index_name: str,
    upload_doc_id: str,
    upload_namespace: str,
    use_semantic_chunking: bool,
    reuse_existing_if_indexed: bool,
    pipeline_state: Dict[str, Any],
    progress=gr.Progress(),
):
    state = dict(pipeline_state or {})
    state.update({"ingestion_happened": False, "dedupe_reuse": False, "last_doc_id": None})
    progress(0.05, desc="Normalizing upload input...")

    data, filename = _normalize_upload(fdsc_file)
    if data is None:
        progress(1.0, desc="No upload supplied")
        return (
            "No upload provided. You can still score using an existing indexed FDSC doc.",
            state,
        )

    if not fdsc_index_name or not upload_doc_id:
        progress(1.0, desc="Missing upload fields")
        return (
            "Upload ignored: provide both FDSC index and upload doc_id.",
            state,
        )

    progress(0.2, desc="Checking existing ingestion metadata...")
    content_hash = _content_sha256(data)
    existing = get_fdsc_document_metadata(fdsc_index_name, upload_doc_id)
    if reuse_existing_if_indexed and existing and str(existing.get("ingestion_status", "indexed")) == "indexed":
        progress(1.0, desc="Reused existing indexed document")
        state.update({"ingestion_happened": False, "dedupe_reuse": True, "last_doc_id": upload_doc_id})
        return (
            f"Dedupe reuse occurred: existing indexed doc '{upload_doc_id}' was reused (no ingestion run).",
            state,
        )

    if reuse_existing_if_indexed:
        # Content-hash reuse works even when the filename or target doc_id differs.
        index_docs = list_fdsc_document_metadata(index_name=fdsc_index_name)
        for doc in index_docs:
            if str(doc.get("ingestion_status", "indexed")) != "indexed":
                continue
            if doc.get("source_content_sha256") == content_hash:
                matched_doc_id = str(doc.get("doc_id") or upload_doc_id)
                progress(1.0, desc="Reused by content hash")
                state.update({"ingestion_happened": False, "dedupe_reuse": True, "last_doc_id": matched_doc_id})
                return (
                    f"Dedupe reuse occurred by content hash: reused indexed doc '{matched_doc_id}' "
                    f"(filename differences ignored).",
                    state,
                )

    progress(0.35, desc="Uploading and ingesting FDSC document...")
    metadata = ingest_fdsc_document(
        fdsc_index_name=fdsc_index_name,
        doc_id=upload_doc_id,
        namespace=upload_namespace or "default",
        filename=filename or "uploaded",
        data=data,
        content_type=None,
        use_semantic_chunking=use_semantic_chunking,
    )
    progress(1.0, desc="Ingestion and indexing complete")
    state.update({"ingestion_happened": True, "dedupe_reuse": False, "last_doc_id": upload_doc_id})
    return (
        f"Ingestion happened for '{upload_doc_id}'. status={metadata.get('ingestion_status')} chunks={metadata.get('chunk_count')}",
        state,
    )


def _score_selected_tir(
    fdsc_index_name: str,
    selected_fdsc_doc_id: str,
    selected_tir_blob: str,
    pipeline_state: Dict[str, Any],
):
    if not fdsc_index_name:
        return "Missing FDSC index.", "", ""
    if not selected_fdsc_doc_id:
        return "Select an FDSC doc prefix to enforce retrieval scoping.", "", ""
    if not selected_tir_blob:
        return "Select a TIR first.", "", ""

    if selected_fdsc_doc_id:
        metadata = get_fdsc_document_metadata(fdsc_index_name, selected_fdsc_doc_id)
        if not metadata:
            return f"Selected FDSC doc '{selected_fdsc_doc_id}' not found.", "", ""
        status = str(metadata.get("ingestion_status", "indexed"))
        if status != "indexed":
            return (
                f"Selected FDSC doc '{selected_fdsc_doc_id}' is not indexed yet (status={status}).",
                "",
                "",
            )

    tir_text = download_tir_file_text(selected_tir_blob)
    retriever = get_fdsc_hybrid_retriever(fdsc_index_name)
    docs = retriever.invoke(tir_text, doc_filter=selected_fdsc_doc_id)

    result = score_single_tir(
        session_id=str(uuid4()),
        fdsc_index_name=fdsc_index_name,
        tir_blob_path=selected_tir_blob,
        config=ScoreSingleTIRConfig(
            retriever=retriever,
            fdsc_doc_filter=selected_fdsc_doc_id,
            persist_result=False,
        ),
    )

    state = pipeline_state or {}
    status = (
        f"Score complete. ingestion_happened={bool(state.get('ingestion_happened'))}, "
        f"dedupe_reuse={bool(state.get('dedupe_reuse'))}, "
        f"retrieved_docs={len(docs)}"
    )
    return status, _format_context_docs(docs), json.dumps(result, indent=2, default=str)


def _refresh_fdsc_dropdown(fdsc_index_name: str, preferred_doc_id: Optional[str] = None):
    choices = _list_fdsc_doc_choices(fdsc_index_name)
    value = None
    if preferred_doc_id and preferred_doc_id in choices:
        value = preferred_doc_id
    elif choices:
        value = choices[0]
    return gr.Dropdown(label="Select existing FDSC doc prefix", choices=choices, value=value)


def _refresh_tir_prefix_dropdown():
    choices = _list_tir_prefix_choices()
    value = choices[0] if choices else None
    return gr.Dropdown(label="Select TIR dataset/prefix", choices=choices, value=value)


def _refresh_tir_dropdown(dataset_prefix: str):
    choices = _list_tir_choices(dataset_prefix)
    value = choices[0] if choices else None
    return gr.Dropdown(label="Select TIR", choices=choices, value=value)


def build_app() -> gr.Blocks:
    with gr.Blocks(title="FDSC/TIR Smoke Test") as demo:
        gr.Markdown("# FDSC Upload + Single-TIR Scoring Smoke Test")

        pipeline_state = gr.State({"ingestion_happened": False, "dedupe_reuse": False, "last_doc_id": None})

        with gr.Row():
            fdsc_index_name = gr.Textbox(label="FDSC Index Name", value="fdsc-index")
            upload_doc_id = gr.Textbox(label="Upload doc_id", placeholder="e.g. fdsc-manual-001")
            upload_namespace = gr.Textbox(label="Upload namespace", value="default")

        with gr.Row():
            fdsc_file = gr.File(label="Upload FDSC Document", file_count="single", type="binary")
            use_semantic_chunking = gr.Checkbox(label="Use semantic chunking", value=True)
            reuse_existing_if_indexed = gr.Checkbox(label="Reuse existing indexed doc (dedupe)", value=True)

        upload_btn = gr.Button("Upload/Reuse FDSC")

        with gr.Row():
            selected_fdsc_doc_id = gr.Dropdown(label="Select existing FDSC doc prefix", choices=[])
            refresh_fdsc_btn = gr.Button("Refresh FDSC Docs")

        with gr.Row():
            tir_prefix = gr.Dropdown(label="Select TIR dataset/prefix", choices=[])
            refresh_tir_prefix_btn = gr.Button("Refresh TIR Prefixes")

        with gr.Row():
            selected_tir_blob = gr.Dropdown(label="Select TIR", choices=[])
            refresh_tir_btn = gr.Button("Refresh TIRs")

        score_btn = gr.Button("Score selected TIR")

        status_text = gr.Textbox(label="Status", lines=4)
        context_text = gr.Textbox(label="Retrieved Context Snippets + Metadata", lines=14)
        score_output = gr.Code(label="Score Result", language="json")

        upload_btn.click(
            fn=_apply_upload_or_reuse,
            inputs=[
                fdsc_file,
                fdsc_index_name,
                upload_doc_id,
                upload_namespace,
                use_semantic_chunking,
                reuse_existing_if_indexed,
                pipeline_state,
            ],
            outputs=[status_text, pipeline_state],
        )

        # Best-effort auto-select of newly ingested or dedupe-matched doc from state.
        pipeline_state.change(
            fn=lambda fdsc_index, state: _refresh_fdsc_dropdown(fdsc_index, (state or {}).get("last_doc_id")),
            inputs=[fdsc_index_name, pipeline_state],
            outputs=[selected_fdsc_doc_id],
        )

        refresh_fdsc_btn.click(
            fn=_refresh_fdsc_dropdown,
            inputs=[fdsc_index_name, selected_fdsc_doc_id],
            outputs=[selected_fdsc_doc_id],
        )

        refresh_tir_prefix_btn.click(
            fn=_refresh_tir_prefix_dropdown,
            inputs=[],
            outputs=[tir_prefix],
        )

        tir_prefix.change(
            fn=_refresh_tir_dropdown,
            inputs=[tir_prefix],
            outputs=[selected_tir_blob],
        )

        refresh_tir_btn.click(
            fn=_refresh_tir_dropdown,
            inputs=[tir_prefix],
            outputs=[selected_tir_blob],
        )

        score_btn.click(
            fn=_score_selected_tir,
            inputs=[fdsc_index_name, selected_fdsc_doc_id, selected_tir_blob, pipeline_state],
            outputs=[status_text, context_text, score_output],
        )

        demo.load(fn=_refresh_fdsc_dropdown, inputs=[fdsc_index_name], outputs=[selected_fdsc_doc_id])
        demo.load(fn=_refresh_tir_prefix_dropdown, inputs=[], outputs=[tir_prefix]).then(
            fn=_refresh_tir_dropdown,
            inputs=[tir_prefix],
            outputs=[selected_tir_blob],
        )

    return demo


if __name__ == "__main__":
    app = build_app()
    app.launch(server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"), server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")))
