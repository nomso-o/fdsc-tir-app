# FDSC RAG & TIR Scoring Web App

## Quickstart (Docker)

```bash
cp .env.example .env
# fill in Azure vars

docker-compose build
docker-compose up
```

## Run locally (no Docker)

### Backend

From `backend/`:
- Create venv (Python 3.11): `python3.11 -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install --upgrade pip && pip install -r requirements.txt`
- Run API: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Verify health: open http://localhost:8000/healthz

### Frontend

From `frontend/`:
- Install deps: `npm install`
- Run dev server: `npm run dev`
- Verify UI: open http://localhost:5173/

### FDSC document ingestion

- Use the UI panel “FDSC Document Manager” (left column) or call `POST /api/fdsc/upload` with `fdsc_index_name`, `doc_id`, and a file. Uploads are stored in the `fdsc-docs` blob container, chunked (semantic chunking defaults to `ENABLE_SEMANTIC_CHUNKING=true`), embedded with Azure OpenAI, and indexed into Azure Cognitive Search using the existing pipeline.
- The upload pipeline now relies on **Azure Document Intelligence** (`AZURE_DOC_INTEL_ENDPOINT` + `AZURE_DOC_INTEL_MODEL_ID`, default `prebuilt-layout`) to extract high-quality paragraphs before chunking. If Document Intelligence cannot parse the file, the service falls back to local text extraction to preserve functionality.
- Upload validation is strict: supported types are `.pdf`, `.docx`, `.txt`, `.md`, file size is capped by `FDSC_UPLOAD_MAX_BYTES` (default 25MB), and ingestion only returns success after chunks are observed in the target search index.
- Document metadata (namespace, chunk counts, semantic flag, ingestion status, source content hash) is stored in the Cosmos DB container `fdsc_documents` and surfaced through `GET /api/fdsc/docs?fdsc_index_name=...` so users can filter TIR scoring to a single FDSC document and see indexing state.
- The scoring UI uses `/api/tir/prefixes` and `/api/fdsc/prefixes` to populate dropdowns of available dataset batches and FDSC documents. These lists are cached briefly server-side and automatically invalidate after new ingest operations, so newly uploaded docs appear immediately.
- Scoring requests validate selected dataset/doc/TIR boundaries before execution. If a selected FDSC doc is not `indexed`, the API returns a clear `409` message instead of running an unscoped score.

### Gradio smoke harness

- A minimal end-to-end harness exists at `scripts/gradio_tir_smoke_test.py`.
- Run it from repo root: `python3 scripts/gradio_tir_smoke_test.py`.
- It supports:
  - upload + ingest with progress,
  - content-hash dedupe reuse (filename-independent),
  - dropdown-driven FDSC/TIR selection,
  - single-TIR scoring with retrieval snippets and structured JSON output.

## Azure resources, roles, and secrets

The app now authenticates to every Azure dependency via Managed Identity and Azure AD tokens.

- **User-assigned managed identity** (UAMI) – grant the identity to App Service/Container Apps/ACI hosting this code.  
  - Required roles: `Storage Blob Data Contributor`, `Search Service Contributor`, `Cosmos DB Built-in Data Contributor`, `Cognitive Services Contributor (OpenAI)`, and `Key Vault Secrets User`.
- **Azure Key Vault** – store secrets that are still needed for legacy integrations:
  - `AZURE_SEARCH_KEY_SECRET_NAME`, `BLOB_STORAGE_KEY_SECRET_NAME`, `COG_SERVICES_KEY_SECRET_NAME`.  
  - The Key Vault URI is referenced via `KEY_VAULT_URI`. The UAMI must have Secret get/list permissions.
- **Azure Blob Storage** – dataset container (`tir-datasets`), results container (`tir-results`), FDSC uploads (`fdsc-docs`), and `tir_scores` for Cosmos-backed summaries. Use the Blob endpoint for `BLOB_ACCOUNT_URL`.
- **Azure Cosmos DB** – stores chat history, structured TIR scores, and FDSC metadata (`fdsc_documents`). Provide the account endpoint and database name.
- **Azure Document Intelligence** – configure `AZURE_DOC_INTEL_ENDPOINT` and (optionally) `AZURE_DOC_INTEL_MODEL_ID` to analyze uploads using Managed Identity auth.
- **Azure Cognitive Search** – hybrid retriever index; auth happens with MI tokens. Populate the index via `infra/setup_azure_endpoints.py`.
- **Azure OpenAI** – both chat + embeddings use Azure AD tokens (scope `https://cognitiveservices.azure.com/.default`).
- **Tunable ingestion settings** – optional environment variables:
  - `FDSC_FIXED_CHUNK_SIZE`, `FDSC_FIXED_CHUNK_OVERLAP`
  - `FDSC_SEMANTIC_MAX_CHARS`, `FDSC_SEMANTIC_MIN_CHARS`, `FDSC_SEMANTIC_HEADING_PATTERN`
  - `FDSC_UPLOAD_MAX_BYTES`, `FDSC_INGESTION_INDEX_TIMEOUT_SECONDS`

If Managed Identity cannot be used (for dev shells), set `USE_MANAGED_IDENTITY=false` and provide temporary connection strings. The configuration validators will fail-fast when required combinations are missing.

## Infrastructure as Code

Two starter templates are provided under `infra/`:

- `infra/bicep/main.bicep` provisions a user-assigned managed identity, Azure Storage, Cosmos DB, Cognitive Search, Azure OpenAI, and Key Vault (with access policies for the MI and an admin object ID).
- `infra/terraform/main.tf` mirrors the same stack using Terraform (Azurerm provider 3.x). Variables cover the base resource name, Key Vault admin object id, location, and tags.

Both templates output the Managed Identity IDs, Key Vault URI, and core service endpoints so you can wire them into `.env`. After deployment:

1. Assign the UAMI to whichever compute host runs the FastAPI/React containers.
2. Create Key Vault secrets for the search/admin keys that external ingestion jobs still require (names must match the values in `.env`).
3. Run `python infra/setup_azure_endpoints.py` to ensure the Cognitive Search index (with `doc_id`/`doc_namespace` fields) exists before starting the backend.
