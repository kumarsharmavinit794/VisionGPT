# VisionGPT
VisionGPT is an AI-powered Vision Language Model platform that analyzes and chats with images, screenshots, charts, UI captures, and visual documents like ChatGPT Vision. Built with FastAPI, PostgreSQL, Ollama, and local vision-capable models such as LLaVA and MiniCPM-V.

## Database

Alembic is not used. On startup, FastAPI calls `init_db()` and SQLAlchemy runs `Base.metadata.create_all()` to create any missing tables safely.

## Run

Development:

```powershell
uvicorn app.main:app --reload --port 8000
```

Production on Windows:

```powershell
start.bat
```

`start.bat` uses Gunicorn when it is available. On native Windows, where Gunicorn is not installable, it falls back to Uvicorn.

Production on Linux:

```sh
sh start.sh
```

Generate a strong secret key:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Health check:

```text
GET /health
```
