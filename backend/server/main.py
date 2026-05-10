from fastapi import FastAPI

from backend.server.config import settings
from backend.server.routes import admin, auth, voice

app = FastAPI(
    title="SG_CUBE",
    description="Local-first AI Operating System — voice-first MVP",
    version="0.3.0",
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(voice.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "version": app.version,
        "supabase_configured": bool(settings.supabase_url and settings.supabase_jwt_secret),
    }
