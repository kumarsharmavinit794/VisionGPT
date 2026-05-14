from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.analysis import ImageAnalysis
from app.models.file import UploadedFile
from app.models.user import User
from app.schemas.analysis import AnalysisRequest, ImageAnalysisOut
from app.services.vision_ai import VisionAIError, VisionAIService
from app.utils.response import APIResponse

router = APIRouter(prefix="/analyze", tags=["analyze"])
vision_ai_service = VisionAIService()


def serialize_analysis(analysis: ImageAnalysis) -> dict:
    return ImageAnalysisOut.model_validate(analysis).model_dump(mode="json")


@router.post("/{file_id}", status_code=status.HTTP_201_CREATED)
async def analyze_file(
    file_id: UUID,
    payload: AnalysisRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UploadedFile).where(UploadedFile.id == file_id, UploadedFile.user_id == current_user.id)
    )
    uploaded = result.scalar_one_or_none()
    if not uploaded:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    prompt = payload.prompt if payload else None
    try:
        result = await vision_ai_service.analyze(uploaded.file_path, prompt)
    except VisionAIError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=APIResponse.error(str(exc), exc.code),
        )

    analysis = ImageAnalysis(
        file_id=uploaded.id,
        summary=result["summary"],
        ocr_text=result["ocr_text"],
        ai_response=result["ai_response"],
        confidence_score=result["confidence_score"],
        json_response=result["json_response"],
        tags=result["tags"],
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    return APIResponse.success(serialize_analysis(analysis), "Analysis created", status.HTTP_201_CREATED)


@router.get("/{file_id}")
async def list_analyses(file_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    file_result = await db.execute(
        select(UploadedFile).where(UploadedFile.id == file_id, UploadedFile.user_id == current_user.id)
    )
    if not file_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    result = await db.execute(
        select(ImageAnalysis).where(ImageAnalysis.file_id == file_id).order_by(ImageAnalysis.created_at.desc())
    )
    return APIResponse.success([serialize_analysis(item) for item in result.scalars().all()])
