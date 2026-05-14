from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class UploadedFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    created_at: datetime


class FileQuery(BaseModel):
    search: str | None = Field(default=None, max_length=255)

    @field_validator("search", mode="before")
    @classmethod
    def strip_search(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value
