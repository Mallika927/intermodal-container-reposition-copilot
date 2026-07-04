# Intermodal Container Reposition Copilot
Agentic AI system recommending empty-container repositioning for
intermodal rail networks, with human-in-the-loop approval.

## Architecture
- backend/: FastAPI + Anthropic SDK. Agent loop orchestrates a
  deterministic scoring tool — the LLM never does arithmetic.
- frontend/: Angular 20, signals-based reactivity, SSE streaming
  for agent reasoning traces.
- All data is synthetic (backend/app/data/), seeded for reproducibility.

## Conventions
- Python: type hints everywhere, pydantic models for all API schemas
- Angular: standalone components, signals over RxJS where possible
- Commits: small, imperative mood ("Add booking forecast generator")

## Commands
- Backend: cd backend && source .venv/bin/activate && uvicorn app.main:app --reload
- Frontend: cd frontend && ng serve
- Tests: cd backend && pytest