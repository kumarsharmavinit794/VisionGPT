@echo off
if not exist logs mkdir logs

where gunicorn >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  gunicorn app.main:app ^
    --workers 4 ^
    --worker-class uvicorn.workers.UvicornWorker ^
    --bind 0.0.0.0:8000 ^
    --timeout 120 ^
    --keep-alive 5 ^
    --max-requests 1000 ^
    --max-requests-jitter 100 ^
    --access-logfile logs\access.log ^
    --error-logfile logs\error.log ^
    --log-level info
) else (
  uvicorn app.main:app ^
    --host 0.0.0.0 ^
    --port 8000 ^
    --timeout-keep-alive 5 ^
    --log-level info
)
