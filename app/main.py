import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text

try:
    from jose import JWTError, jwt
except ModuleNotFoundError:
    JWTError = ValueError
    jwt = None

try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.util import get_remote_address
except ModuleNotFoundError:
    Limiter = None
    RateLimitExceeded = None
    SlowAPIMiddleware = None
    get_remote_address = None

try:
    from structlog.contextvars import bind_contextvars, clear_contextvars
except ModuleNotFoundError:
    def bind_contextvars(**kwargs):
        return None

    def clear_contextvars():
        return None

from app.api import analyze, auth, chat, files
from app.core.config import settings
from app.core.logging import logger
from app.db.init_db import init_db
from app.db.session import engine
from app.utils.response import APIResponse

APP_START_TIME = time.monotonic()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "font-src 'self' https://cdn.jsdelivr.net;"
        )
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid4())
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        user_id = self._extract_user_id(request)

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
                user_id=user_id,
            )
            if "response" in locals():
                response.headers["X-Request-ID"] = request_id

    @staticmethod
    def _extract_user_id(request: Request) -> str | None:
        authorization = request.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            return None
        if jwt is None:
            return None
        token = authorization.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError:
            return None
        return payload.get("sub")


limiter = None
if Limiter is not None:
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
    )

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
)
if limiter is not None:
    app.state.limiter = limiter

if SlowAPIMiddleware is not None:
    app.add_middleware(SlowAPIMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router)
app.include_router(files.router)
app.include_router(analyze.router)
app.include_router(chat.router, prefix="/chat")


def print_registered_routes() -> None:
    for route in app.routes:
        print(route.path)


@app.on_event("startup")
async def startup_event():
    Path(settings.LOG_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    analyze.vision_ai_service.validate_preprocessing_settings()
    await init_db()
    print_registered_routes()

    ollama_available = await check_ollama()
    if not ollama_available:
        logger.warning("ollama_unavailable", base_url=settings.OLLAMA_BASE_URL)

    workers = os.getenv("WEB_CONCURRENCY", "1")
    logger.info(
        "Vision AI started",
        env=settings.ENVIRONMENT,
        workers=workers,
    )


@app.on_event("shutdown")
async def shutdown_event():
    await analyze.vision_ai_service.close()
    await chat.vision_ai_service.close()
    if engine is not None:
        await engine.dispose()
    logger.info("Vision AI shutting down gracefully")


@app.get("/health")
async def health_check():
    database_status = "connected"
    try:
        if engine is None:
            raise RuntimeError("Database driver unavailable")
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        database_status = "error"
        logger.error("database_health_check_failed", exc_info=True)

    ollama_status, models_available = await get_ollama_status()
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "database": database_status,
        "ollama": ollama_status,
        "models_available": models_available,
        "uptime_seconds": int(time.monotonic() - APP_START_TIME),
    }


async def check_ollama() -> bool:
    status_name, _ = await get_ollama_status()
    return status_name == "connected"


async def get_ollama_status() -> tuple[str, list[str]]:
    try:
        async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT) as client:
            response = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
    except Exception:
        return "unavailable", []

    payload = response.json()
    models = [item.get("name") for item in payload.get("models", []) if item.get("name")]
    return "connected", models


if RateLimitExceeded is not None:
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=APIResponse.error("Rate limit exceeded", "RATE_LIMIT_EXCEEDED", str(exc)),
        )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=APIResponse.error("Not found", "NOT_FOUND"),
    )


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        content=APIResponse.error("Method not allowed", "METHOD_NOT_ALLOWED"),
    )


@app.exception_handler(422)
async def validation_status_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=APIResponse.error("Validation error", "VALIDATION_ERROR", getattr(exc, "detail", None)),
    )


@app.exception_handler(500)
async def internal_status_handler(request: Request, exc: StarletteHTTPException):
    logger.error("internal_server_error", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=APIResponse.error("Internal server error", "INTERNAL_ERROR"),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=APIResponse.error("Validation error", "VALIDATION_ERROR", errors),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = "HTTP_ERROR"
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "UNAUTHORIZED"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = "FORBIDDEN"
    elif exc.status_code == status.HTTP_409_CONFLICT:
        code = "CONFLICT"
    return JSONResponse(
        status_code=exc.status_code,
        content=APIResponse.error(str(exc.detail), code),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", path=request.url.path, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=APIResponse.error("Internal server error", "INTERNAL_ERROR"),
    )
