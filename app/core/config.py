import json
import os
from pathlib import Path
from typing import List

from pydantic import BaseModel, ConfigDict, field_validator

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ModuleNotFoundError:
    SettingsConfigDict = ConfigDict

    class BaseSettings(BaseModel):
        def __init__(self, **data):
            env_data = {}
            env_file = Path(".env")
            if env_file.exists():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    env_data[key.strip()] = value.strip()
            env_data.update(os.environ)

            for name, field in self.__class__.model_fields.items():
                if name in data or name not in env_data:
                    continue
                data[name] = self._coerce_env_value(env_data[name], field.annotation)

            super().__init__(**data)

        @staticmethod
        def _coerce_env_value(value: str, annotation):
            if annotation is bool:
                return value.lower() in {"1", "true", "yes", "on"}
            if annotation is int:
                return int(value)
            if annotation in {list, List[str]} or getattr(annotation, "__origin__", None) is list:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return [item.strip() for item in value.split(",") if item.strip()]
            return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    APP_NAME: str = "Vision AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/visionai"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # Auth
    SECRET_KEY: str = "change-this-to-a-random-secret-key-minimum-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Ollama vision
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llava"
    OLLAMA_TIMEOUT: int = 60

    # Image preprocessing for VLM requests. These defaults keep payloads small
    # and let older .env files start cleanly even if the keys are absent.
    VLM_MAX_IMAGE_SIZE: int = 1024
    VLM_IMAGE_QUALITY: int = 85

    # Upload
    UPLOAD_DIR: str = "app/uploads"
    MAX_FILE_SIZE_MB: int = 20
    ALLOWED_EXTENSIONS: List[str] = ["png", "jpg", "jpeg", "webp"]

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    @field_validator("OLLAMA_TIMEOUT", mode="before")
    @classmethod
    def validate_ollama_timeout(cls, value):
        return cls._bounded_int(value, default=60, minimum=5, maximum=300)

    @field_validator("VLM_MAX_IMAGE_SIZE", mode="before")
    @classmethod
    def validate_vlm_max_image_size(cls, value):
        return cls._bounded_int(value, default=1024, minimum=256, maximum=2048)

    @field_validator("VLM_IMAGE_QUALITY", mode="before")
    @classmethod
    def validate_vlm_image_quality(cls, value):
        return cls._bounded_int(value, default=85, minimum=40, maximum=95)

    @staticmethod
    def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if minimum <= parsed <= maximum else default


settings = Settings()
