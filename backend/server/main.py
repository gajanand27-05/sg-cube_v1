import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.server.config import settings
from backend.server.routes import admin, auth, execute, memory, orchestrate, remote, ui, vision, voice

log = logging.getLogger(__name__)

app = FastAPI(
    title="SG_CUBE",
    description="Local-first AI Operating System — agentic build",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(voice.router)
app.include_router(orchestrate.router)
app.include_router(execute.router)
app.include_router(remote.router)
app.include_router(ui.router)
app.include_router(vision.router)
app.include_router(memory.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "version": app.version,
        "supabase_configured": bool(settings.supabase_url and settings.supabase_jwt_secret),
    }


@app.get("/api/health")
def api_health():
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "version": app.version,
        "supabase_configured": bool(settings.supabase_url and settings.supabase_jwt_secret),
    }


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    log.info(f"Serving frontend from {FRONTEND_DIST}")
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
