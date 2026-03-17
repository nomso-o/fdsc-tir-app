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

## Azure resources, roles, and secrets

The app now authenticates to every Azure dependency via Managed Identity and Azure AD tokens.

- **User-assigned managed identity** (UAMI) – grant the identity to App Service/Container Apps/ACI hosting this code.  
  - Required roles: `Storage Blob Data Contributor`, `Search Service Contributor`, `Cosmos DB Built-in Data Contributor`, `Cognitive Services Contributor (OpenAI)`, and `Key Vault Secrets User`.
- **Azure Key Vault** – store secrets that are still needed for legacy integrations:
  - `AZURE_SEARCH_KEY_SECRET_NAME`, `BLOB_STORAGE_KEY_SECRET_NAME`, `COG_SERVICES_KEY_SECRET_NAME`.  
  - The Key Vault URI is referenced via `KEY_VAULT_URI`. The UAMI must have Secret get/list permissions.
- **Azure Blob Storage** – dataset container (`tir-datasets`), results container (`tir-results`), and `tir_scores` for Cosmos-backed summaries. Use the Blob endpoint for `BLOB_ACCOUNT_URL`.
- **Azure Cosmos DB** – stores chat history and structured TIR scores. Provide the account endpoint and database name.
- **Azure Cognitive Search** – hybrid retriever index; auth happens with MI tokens. Populate the index via `infra/setup_azure_endpoints.py`.
- **Azure OpenAI** – both chat + embeddings use Azure AD tokens (scope `https://cognitiveservices.azure.com/.default`).

If Managed Identity cannot be used (for dev shells), set `USE_MANAGED_IDENTITY=false` and provide temporary connection strings. The configuration validators will fail-fast when required combinations are missing.

## Infrastructure as Code

Two starter templates are provided under `infra/`:

- `infra/bicep/main.bicep` provisions a user-assigned managed identity, Azure Storage, Cosmos DB, Cognitive Search, Azure OpenAI, and Key Vault (with access policies for the MI and an admin object ID).
- `infra/terraform/main.tf` mirrors the same stack using Terraform (Azurerm provider 3.x). Variables cover the base resource name, Key Vault admin object id, location, and tags.

Both templates output the Managed Identity IDs, Key Vault URI, and core service endpoints so you can wire them into `.env`. After deployment:

1. Assign the UAMI to whichever compute host runs the FastAPI/React containers.
2. Create Key Vault secrets for the search/admin keys that external ingestion jobs still require (names must match the values in `.env`).
3. Run `python infra/setup_azure_endpoints.py` to ensure the Cognitive Search index exists before starting the backend.
