# Gradio Smoke Test Harness

## Run Locally

From repo root:

```bash
python3 scripts/gradio_tir_smoke_test.py
```

Then open the Gradio URL shown in the terminal (default: `http://0.0.0.0:7860` / `http://localhost:7860`).

## Prerequisites

This harness calls backend ingestion/retrieval/scoring code directly, so the same backend dependencies and Azure connectivity are required.

1. Python environment with backend dependencies installed:
```bash
pip install -r backend/requirements.txt
```

2. Environment variables configured (typically from `.env`) so `backend.app.config` can initialize successfully.

3. Connectivity and permissions to required services:
- Azure OpenAI (chat + embeddings)
- Azure Cognitive Search index access (read/write for ingestion + retrieval)
- Azure Blob Storage access (`tir-datasets`, `fdsc-docs`, and related containers)
- Azure Cosmos DB access (`fdsc_documents`, `tir_scores`, etc.)
- Azure Document Intelligence endpoint access (for ingestion extraction)

4. Existing TIR dataset blobs under a valid prefix so the TIR dropdown can populate.

## Known-Good Manual Checklist

1. Upload a new FDSC doc
- Set `FDSC Index Name`, `Upload doc_id`, namespace, and pick a file.
- Click **Upload/Reuse FDSC**.
- Expect status to indicate ingestion/indexing completed and FDSC dropdown updated.

2. Re-upload the same doc (dedupe reuse)
- Leave **Reuse existing indexed doc (dedupe)** checked.
- Upload with the same file content (doc_id and filename may be different).
- Expect status like “Dedupe reuse occurred ... no ingestion run” or “... by content hash ...”.

3. Score one TIR
- Select an indexed FDSC doc, then a TIR dataset prefix and a specific TIR from dropdown.
- Click **Score selected TIR**.
- Expect status showing retrieval doc count and JSON score output.

4. Validate retrieval filtered to selected doc
- Select the uploaded/desired FDSC doc in dropdown.
- Score the same TIR again.
- In **Retrieved Context Snippets + Metadata**, verify all `doc_id` values match the selected FDSC doc (exact filter).

## Task Runner Target

This repo currently does **not** include a `Makefile`, `Taskfile`, or `noxfile`, so no extra target was added.
Use the direct command:

```bash
python3 scripts/gradio_tir_smoke_test.py
```
