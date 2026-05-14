from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnalysisRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=2000)

    @field_validator("prompt", mode="before")
    @classmethod
    def strip_prompt(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class ImageAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_id: UUID
    summary: str | None = None
    ocr_text: str | None = None
    ai_response: str | None = None
    confidence_score: float | None = None
