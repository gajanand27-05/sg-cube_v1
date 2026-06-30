import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.server.config import settings
from backend.server.routes import admin, agents, auth, diagnostics, execute, files, memory, orchestrate, remote, system, ui, vision, voice

# Initialize LLM provider at startup
from backend.ai_modules.llm import create_llm_provider

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_llm_provider()
    log.info("LLM provider initialized")
    yield
    log.info("Shutting down")


app = FastAPI(
    title="SG_CUBE",
    description="Local-first AI Operating System — agentic build",
    version="1.0.0",
    lifespan=lifespan,
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
app.include_router(agents.router)
app.include_router(system.router)
app.include_router(files.router)
app.include_router(diagnostics.router)

# Phase E: Optionally mount MCP server at /mcp
try:
    from backend.core.mcp_server import mcp_app
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)
        log.info("MCP server mounted at /mcp")
    else:
        log.debug("MCP server not mounted: fastmcp not installed")
except Exception as e:
    log.debug("MCP server not mounted: %s", e)


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
