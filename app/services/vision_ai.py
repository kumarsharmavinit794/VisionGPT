import asyncio
import base64
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_VISION_MODELS = ("minicpm-v", "llava", "bakllava", "qwen2.5vl")
DEFAULT_MAX_IMAGE_SIZE = 1024
DEFAULT_IMAGE_QUALITY = 85
MAX_IMAGE_PIXELS = 25_000_000


class VisionAIError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503, code: str = "VISION_AI_ERROR") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class VisionAIService:
    def __init__(self) -> None:
        self.ollama_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.timeout = httpx.Timeout(float(settings.OLLAMA_TIMEOUT))
        self.max_image_size = self.get_int_setting("VLM_MAX_IMAGE_SIZE", DEFAULT_MAX_IMAGE_SIZE, 256, 2048)
        self.image_quality = self.get_int_setting("VLM_IMAGE_QUALITY", DEFAULT_IMAGE_QUALITY, 40, 95)
        self._client: httpx.AsyncClient | None = None
        self._model_cache: str | None = None

    async def analyze(self, file_path: str, prompt: str | None = None) -> dict[str, Any]:
        started_at = time.perf_counter()
        path = Path(file_path)
        if not path.exists():
            raise VisionAIError("Uploaded file not found on disk", status_code=404, code="FILE_NOT_FOUND")
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise VisionAIError(
                "Only PNG, JPG, JPEG, and WEBP images are supported by the Ollama vision workflow",
                status_code=415,
                code="UNSUPPORTED_IMAGE_FORMAT",
            )
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if path.stat().st_size > max_bytes:
            raise VisionAIError("Uploaded image is too large", status_code=413, code="IMAGE_TOO_LARGE")

        model_used = await self.get_vision_model()
        image_payload = await asyncio.to_thread(self.preprocess_image, path)
        final_prompt = self.build_prompt(prompt)

        inference_started_at = time.perf_counter()
        ai_response = await self.generate_image_response(model_used, final_prompt, image_payload["base64"])
        inference_seconds = time.perf_counter() - inference_started_at
        parsed_response = self.parse_model_response(ai_response)

        summary = parsed_response.get("summary") or self.extract_summary(ai_response)
        visible_text = parsed_response.get("visible_text") or ""
        detailed_response = parsed_response.get("ai_response") or ai_response
        confidence_score = self.extract_confidence(parsed_response, detailed_response, visible_text)
        processing_seconds = time.perf_counter() - started_at

        logger.info(
            "vision_analysis_completed",
            model=model_used,
            image_original_size=image_payload["original_size"],
            image_inference_size=image_payload["inference_size"],
            image_payload_bytes=image_payload["payload_bytes"],
            inference_seconds=round(inference_seconds, 3),
            processing_seconds=round(processing_seconds, 3),
        )

        return {
            "summary": summary,
            "ocr_text": visible_text,
            "ai_response": detailed_response,
            "confidence_score": confidence_score,
            "json_response": {
                "model": model_used,
                "prompt": prompt,
                "visible_text_source": "ollama_vision_model",
                "inference_seconds": round(inference_seconds, 3),
                "processing_seconds": round(processing_seconds, 3),
                "image_original_size": image_payload["original_size"],
                "image_inference_size": image_payload["inference_size"],
            },
            "tags": self.extract_tags(detailed_response),
        }

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def get_vision_model(self) -> str:
        if self._model_cache:
            return self._model_cache

        available_models = await self.get_available_models()
        if not available_models:
            raise VisionAIError(
                "Ollama is unavailable or returned no installed models",
                status_code=503,
                code="OLLAMA_UNAVAILABLE",
            )

        for desired_model in self.model_priority():
            resolved_model = self.resolve_model_name(desired_model, available_models)
            if resolved_model:
                self._model_cache = resolved_model
                return resolved_model

        raise VisionAIError(
            "No supported Ollama vision model is installed. Run: ollama pull llava or ollama pull minicpm-v",
            status_code=503,
            code="OLLAMA_MODEL_MISSING",
        )

    async def get_available_models(self) -> set[str]:
        try:
            client = await self.get_client()
            response = await client.get(f"{self.ollama_url}/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("ollama_model_check_failed", error=str(exc))
            return set()

        data = response.json()
        names = {item.get("name") for item in data.get("models", []) if item.get("name")}
        models = {item.get("model") for item in data.get("models", []) if item.get("model")}
        return names | models

    def preprocess_image(self, path: Path) -> dict[str, Any]:
        try:
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                original_size = image.size
                total_pixels = original_size[0] * original_size[1]
                if total_pixels > MAX_IMAGE_PIXELS:
                    raise VisionAIError("Uploaded image dimensions are too large", status_code=413, code="IMAGE_TOO_LARGE")
                # Use validated instance settings so older Settings objects or
                # incomplete .env files cannot crash the request path.
                image.thumbnail((self.max_image_size, self.max_image_size), self.lanczos_filter())
                inference_size = image.size
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=self.image_quality, optimize=True)
        except (UnidentifiedImageError, OSError) as exc:
            logger.warning("image_preprocessing_failed", file_path=str(path), error=str(exc))
            raise VisionAIError("Uploaded file is not a readable image", status_code=400, code="INVALID_IMAGE") from exc
        except Image.DecompressionBombError as exc:
            logger.warning("image_preprocessing_decompression_bomb", file_path=str(path), error=str(exc))
            raise VisionAIError("Uploaded image dimensions are too large", status_code=413, code="IMAGE_TOO_LARGE") from exc
        except Exception as exc:
            if isinstance(exc, VisionAIError):
                raise
            logger.warning("image_preprocessing_unexpected_error", file_path=str(path), error=str(exc))
            raise VisionAIError("Image preprocessing failed before vision analysis", status_code=400, code="IMAGE_PREPROCESSING_FAILED") from exc

        payload = buffer.getvalue()
        return {
            "base64": base64.b64encode(payload).decode("utf-8"),
            "original_size": f"{original_size[0]}x{original_size[1]}",
            "inference_size": f"{inference_size[0]}x{inference_size[1]}",
            "payload_bytes": len(payload),
        }

    async def generate_image_response(self, model: str, prompt: str, base64_image: str) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [base64_image],
            "stream": False,
        }

        try:
            client = await self.get_client()
            response = await client.post(f"{self.ollama_url}/api/generate", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("ollama_vision_timeout", model=model, timeout_seconds=settings.OLLAMA_TIMEOUT)
            raise VisionAIError(
                "Ollama vision analysis timed out. Try a smaller image or a faster model such as minicpm-v",
                status_code=504,
                code="OLLAMA_TIMEOUT",
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("ollama_vision_http_error", model=model, status_code=exc.response.status_code)
            raise VisionAIError(
                f"Ollama vision request failed with status {exc.response.status_code}",
                status_code=502,
                code="OLLAMA_HTTP_ERROR",
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("ollama_vision_request_failed", model=model, error=str(exc))
            raise VisionAIError(f"Ollama vision request failed: {exc}", status_code=503, code="OLLAMA_REQUEST_FAILED") from exc

        model_response = (response.json().get("response") or "").strip()
        if not model_response or model_response == prompt:
            raise VisionAIError("Ollama returned an empty or invalid vision response", status_code=502, code="EMPTY_MODEL_RESPONSE")
        return model_response

    @staticmethod
    def build_prompt(prompt: str | None) -> str:
        user_prompt = prompt or "Analyze this image and explain the important visual and textual information."
        return (
            "You are a production Vision AI assistant. Analyze the attached image directly.\n"
            "Use only your vision capability to read any visible text. Do not mention external tools.\n"
            "Return only valid JSON with these keys:\n"
            "{\n"
            '  "summary": "one short summary",\n'
            '  "visible_text": "all visible readable text, or empty string",\n'
            '  "ai_response": "detailed visual and textual analysis",\n'
            '  "confidence_score": 0.0\n'
            "}\n"
            "The confidence_score must be a number from 0 to 1.\n\n"
            f"User request: {user_prompt}"
        )

    @staticmethod
    def parse_model_response(ai_response: str) -> dict[str, Any]:
        text = ai_response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        json_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not json_match:
            return {}

        try:
            parsed = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def model_priority() -> list[str]:
        candidates = [settings.OLLAMA_MODEL, *DEFAULT_VISION_MODELS]
        ordered: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in ordered:
                ordered.append(candidate)
        return ordered

    @staticmethod
    def resolve_model_name(desired_model: str, available_models: set[str]) -> str | None:
        if desired_model in available_models:
            return desired_model
        desired_base = desired_model.split(":", 1)[0]
        for model_name in available_models:
            if model_name.split(":", 1)[0] == desired_base:
                return model_name
        return None

    @staticmethod
    def get_int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
        value = getattr(settings, name, None)
        if value is None:
            logger.warning("vision_setting_missing_using_default", setting=name, default=default)
            return default

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            logger.warning("vision_setting_invalid_using_default", setting=name, value=value, default=default)
            return default

        if minimum <= parsed <= maximum:
            return parsed

        logger.warning(
            "vision_setting_out_of_range_using_default",
            setting=name,
            value=parsed,
            minimum=minimum,
            maximum=maximum,
            default=default,
        )
        return default

    @staticmethod
    def lanczos_filter():
        return getattr(getattr(Image, "Resampling", Image), "LANCZOS")

    @staticmethod
    def validate_preprocessing_settings() -> None:
        env_file = Path(".env")
        env_text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        if "VLM_MAX_IMAGE_SIZE" not in os.environ and "VLM_MAX_IMAGE_SIZE=" not in env_text:
            logger.warning(
                "vlm_max_image_size_missing_using_default",
                default=getattr(settings, "VLM_MAX_IMAGE_SIZE", DEFAULT_MAX_IMAGE_SIZE),
            )

        max_image_size = VisionAIService.get_int_setting(
            "VLM_MAX_IMAGE_SIZE",
            DEFAULT_MAX_IMAGE_SIZE,
            256,
            2048,
        )
        image_quality = VisionAIService.get_int_setting(
            "VLM_IMAGE_QUALITY",
            DEFAULT_IMAGE_QUALITY,
            40,
            95,
        )
        logger.info(
            "vision_preprocessing_settings_validated",
            max_image_size=max_image_size,
            image_quality=image_quality,
            resampling_filter="LANCZOS",
        )

    @staticmethod
    def extract_summary(ai_response: str) -> str:
        if not ai_response:
            return "No AI response generated."
        first_paragraph = ai_response.strip().split("\n\n", 1)[0]
        return first_paragraph[:1000]

    @staticmethod
    def extract_confidence(parsed_response: dict[str, Any], ai_response: str, visible_text: str) -> float:
        parsed_confidence = parsed_response.get("confidence_score")
        if isinstance(parsed_confidence, (int, float)):
            return max(0.0, min(1.0, float(parsed_confidence)))

        match = re.search(r"confidence(?:\s*score)?\D+([01](?:\.\d+)?)", ai_response, re.IGNORECASE)
        if match:
            return max(0.0, min(1.0, float(match.group(1))))
        if ai_response and visible_text:
            return 0.86
        if ai_response:
            return 0.72
        return 0.0

    @staticmethod
    def extract_tags(ai_response: str) -> list[str]:
        words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{3,}\b", ai_response.lower())
        ignored = {"this", "that", "with", "from", "image", "text", "summary", "confidence"}
        tags: list[str] = []
        for word in words:
            if word not in ignored and word not in tags:
                tags.append(word)
            if len(tags) == 8:
                break
        return tags
