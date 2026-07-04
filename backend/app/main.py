from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router

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
