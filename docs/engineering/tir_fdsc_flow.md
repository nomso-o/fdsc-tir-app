# TIR + FDSC Flow Map

This document describes the current data flow for scoring Test Incident Reports (TIRs) against Failure Definition & Scoring Criteria (FDSC) content, from API entry points through storage layers and retrieval.

## Core entry points

- **FastAPI models (`backend/app/models/schemas.py`)**
  - `ChatRequest` / `ChatResponse` drive the conversational RAG endpoint. Inputs: `message`, `session_id`, `fdsc_index_name`.
  - `TIRScoreRequest` / `TIRScoreResponse` handle dataset scoring. Inputs: `session_id`, `fdsc_index_name`, `dataset_prefix`, optional `fdsc_doc_id`, optional `tir_blob_path`. Request validators enforce prefix/path safety and ensure selected TIR is under the selected dataset prefix.
  - `SaveEditedRequest` updates markdown exports per TIR.
- **API handlers (`backend/app/main.py`)**
  - `POST /api/chat/message` builds a chat runnable via `build_fdsc_chat_runnable(fdsc_index_name)` and invokes it with the session-specific Cosmos-backed chat history.
  - `POST /api/tir/score` is the main TIR scoring flow. It first validates selected dataset/doc/TIR existence and ingestion status, then calls `score_tir_dataset(session_id, fdsc_index_name, dataset_prefix, fdsc_doc_id, tir_blob_path)` and materializes `TIRSingleResult` models (including `tir_id` and `dataset_prefix`).
  - `POST /api/tir/save` uploads edited markdown to blob storage and mirrors changes in Cosmos DB.
  - `GET /api/tir/export/*` fetch saved structured results and streams DOCX/PDF exports.
- **Frontend panels**
  - `frontend/src/components/TIRAnalysisPanel.tsx` loads FDSC/TIR prefixes from APIs and sends `sessionId`, `fdscIndexName`, selected `datasetPrefix`, and optional selected `fdsc_doc_id` to `/api/tir/score`.
  - `frontend/src/components/ChatPanel.tsx` mirrors the same `fdscIndexName` concept for the chat surface.

## Storage + metadata layers

- **Azure Blob Storage (`backend/app/services/storage_service.py`)**
  - Containers are hard-coded: `tir-datasets` (raw TIR text files), `tir-results` (markdown exports), `fdsc-docs` (uploaded FDSC sources), `tir_scores` (Cosmos logical container name, see below).
  - `list_tir_files(prefix)` enumerates dataset blobs that match `dataset_prefix`. This is where the prefix ultimately resolves—users provide a logical folder-like name (e.g., `fdsc-batch-2024-09`). Azure’s SDK matches blobs whose names start with the provided prefix, enabling per-batch scoring.
  - `download_tir_file_text` fetches each blob before scoring.
  - `upload_result_markdown` stores edited results.
- **Azure Cosmos DB (`backend/app/services/storage_service.py`, `backend/app/rag/history.py`)**
  - TIR scoring results persist to the `tir_scores` container via `save_structured_results`. The Cosmos document schema: `id` + `session_id` + `results` array.
  - Per-TIR updates use `upsert_structured_result`, with uniqueness keyed by `(tir_blob_path, fdsc_doc_filter)` within a session to avoid silent duplicates for the same scoring identity.
  - Chat history is stored in the `chat_history` container using `CosmosDBChatMessageHistory`, which serializes LangChain messages with `messages_to_dict`.
  - Uploaded FDSC documents are cataloged in `fdsc_documents` with ingestion metadata including `ingestion_status` and `source_content_sha256`.
- **Azure Cognitive Search (`backend/app/rag/retriever.py`, `infra/setup_azure_endpoints.py`)**
  - Index name is variable (`fdsc_index_name` input). The index schema (set up via `infra/setup_azure_endpoints.py`) includes searchable text (`content`), metadata (`id`, `page`, `blob_uri`), and `content_vector` for vector search.
  - `FDSCHybridRetriever` wraps Azure Search, performing hybrid queries using both keyword (`search_text`) and `Vector` search against the `content_vector` field. Embeddings use Azure OpenAI (`backend/app/azure_clients.py:embeddings`).

## Retrieval and scoring pipeline

### Chat RAG (`backend/app/rag/chat_rag.py`)

1. The runnable refines user questions (`_query_refine_chain`), pulls context snippets via `get_fdsc_hybrid_retriever(fdsc_index_name)`, then calls `_answer_chain` (LangChain LCEL) using Azure OpenAI Chat.
2. Retrieval occurs with the same hybrid search described above; references are returned as source documents with `id/page/blob_uri`.

### FDSC ingestion (`backend/app/pipelines/fdsc_ingestion.py`)

1. `POST /api/fdsc/upload` receives `fdsc_index_name`, `doc_id`, optional namespace / semantic flag, and a file to ingest.
2. The pipeline calls Azure Document Intelligence (`DocumentIntelligenceClient`) using `AZURE_DOC_INTEL_ENDPOINT` + `AZURE_DOC_INTEL_MODEL_ID` to extract paragraphs/structured content directly from the upload. If Document Intelligence fails, the service falls back to local PDF/DOCX/plain-text extraction.
3. `_select_chunker` merges the extracted text using semantic/fixed chunkers (feature-flagged via `ENABLE_SEMANTIC_CHUNKING` and tunable via `FDSC_FIXED_*` / `FDSC_SEMANTIC_*` settings).
4. Chunks are embedded with Azure OpenAI embeddings, existing chunks for the doc are deleted from the Azure Cognitive Search index, and new documents (with metadata fields `doc_id`, `doc_namespace`, `chunk_index`, `source_file`) are uploaded.
5. Source files are stored in the `fdsc-docs` container; metadata is persisted to Cosmos via `upsert_fdsc_document_metadata`, and ingestion waits for search indexing readiness before returning success (`ingestion_status=indexed`).

### TIR scoring (`backend/app/rag/tir_scoring.py`)

1. `score_single_tir(session_id, fdsc_index_name, tir_blob_path, config)` is the core primitive:
   - Loads the TIR body from blob storage.
   - Retrieves FDSC snippets via a hybrid retriever (reusing an injected retriever if provided) and filters by exact `doc_id` when `fdsc_doc_filter` is supplied.
   - Runs `_run_scoring_agents` (formerly the “single TIR” helper) to execute all LangChain agents.
   - Persists the result immediately using `upsert_structured_result`, guaranteeing Cosmos DB stays in sync per TIR.
   - Emits structured logging with retrieval hit counts, retrieval mode, and elapsed time.
2. `score_tir_dataset(session_id, fdsc_index_name, dataset_blob_prefix, fdsc_doc_filter, tir_blob_path)` now orchestrates the loop only:
   - Builds a retriever once and creates a shared `ScoreSingleTIRConfig`.
   - Calls `score_single_tir` for each blob under the prefix (or one blob when `tir_blob_path` is provided), collecting the returned dicts for the API response while persistence happens inside the primitive.

### Outputs

- `score_single_tir` returns a dict with JSON fragments for each agent plus `rationale`, `markdown_table`, `technical_review`, `alignment_review`, `tir_id`, `dataset_prefix`, `fdsc_doc_filter`, and the source `tir_blob_path`.
- `score_tir_dataset` aggregates them, so the public API receives structured `TIRSingleResult` models.

## Prefix handling overview

- Frontend fetches dataset options via `/api/tir/prefixes` which calls `list_tir_prefixes()`; this function enumerates blob prefixes from Azure Storage, dedupes/sorts them, and caches the list for 60 seconds.
- Server-side validators (Pydantic score request validators) strip leading `/`, reject `//`, `.`, or `..` segments, validate optional TIR path safety, and enforce that selected TIR belongs to the selected dataset prefix.
- Blob listing simply uses `container.list_blobs(name_starts_with=prefix)`—no additional delimiter logic—so the effective namespace is whatever naming convention ingestion jobs used (e.g., `customerA/batch1/file.txt`).
- FDSC documents are listed via `/api/fdsc/prefixes?fdsc_index_name=...`; this reads from the Cosmos `fdsc_documents` container, surfaces user-friendly labels (doc id + namespace), and caches per-index results until a new upload invalidates the cache. Analysts can filter scoring by selecting a `fdsc_doc_id`, and scoring is blocked unless that doc is `indexed`.

## Retrieval touchpoints summary

- **Chat RAG** uses the hybrid retriever with refined natural language questions. Output citations drive the frontend chat UI.
- **TIR scoring** calls the same retriever but seeds it with entire TIR texts, effectively using the TIR body as the query to fetch relevant FDSC guidance prior to classification.

With this map, future work (e.g., adding a single-TIR scoring endpoint or wiring ingestion scripts) can target the specific modules involved without reverse-engineering the current flow.
