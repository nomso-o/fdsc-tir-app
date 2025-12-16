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
- Create venv (Python 3.12): `python3.12 -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install --upgrade pip && pip install -r requirements.txt`
- Run API: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- Verify health: open http://localhost:8000/healthz

### Frontend

From `frontend/`:
- Install deps: `npm install`
- Run dev server: `npm run dev`
- Verify UI: open http://localhost:5173/
