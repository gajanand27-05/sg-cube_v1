@echo off
rem Prefer the project venv — running on the system interpreter caused the
rem qrcode/torch split-brain (packages installed in one Python, daemon on the other).
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m backend.daemon.main %*
) else (
  python -m backend.daemon.main %*
)
