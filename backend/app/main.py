from pathlib import Path

from dotenv import load_dotenv

# Anchored to this file's path so .env loads regardless of the working
# directory uvicorn is launched from. Must run before any app-package
# import, since those may instantiate pydantic-settings classes.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.routes import router as api_router  # noqa: E402

app = FastAPI(
    title="Intermodal Container Reposition Copilot",
    description="Agentic AI for empty-container repositioning with human-in-the-loop approval",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok", "service": "reposition-copilot-api"}
