from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.file import UploadedFile
from app.models.user import User
from app.schemas.file import UploadedFileOut
from app.utils.response import APIResponse

router = APIRouter(prefix="/files", tags=["files"])

try:
    import multipart  # noqa: F401
    HAS_MULTIPART = True
except ModuleNotFoundError:
    HAS_MULTIPART = False

try:
    import aiofiles
except ModuleNotFoundError:
    aiofiles = None


def serialize_file(uploaded_file: UploadedFile) -> dict:
    return UploadedFileOut.model_validate(uploaded_file).model_dump(mode="json")


if HAS_MULTIPART:
    @router.post("/upload", status_code=status.HTTP_201_CREATED)
    async def upload_file(
        file: UploadFile = File(...),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        original_name = file.filename or "upload"
        extension = Path(original_name).suffix.lower().lstrip(".")
        if extension not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File type is not allowed")

        content = await file.read()
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if len(content) > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large")

        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid4()}.{extension}"
        file_path = upload_dir / stored_name
        if aiofiles is None:
            file_path.write_bytes(content)
        else:
            async with aiofiles.open(file_path, "wb") as out_file:
                await out_file.write(content)

        uploaded = UploadedFile(
            user_id=current_user.id,
            filename=stored_name,
            original_filename=original_name.strip()[:255],
            file_path=str(file_path),
            file_type=file.content_type or extension,
            file_size=len(content),
        )
        db.add(uploaded)
        await db.commit()
        await db.refresh(uploaded)
        return APIResponse.success(serialize_file(uploaded), "File uploaded", status.HTTP_201_CREATED)


@router.get("")
async def list_files(
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    base_query = select(UploadedFile).where(UploadedFile.user_id == current_user.id)
    total = await db.scalar(select(func.count()).select_from(base_query.subquery()))
    result = await db.execute(
        base_query.order_by(UploadedFile.created_at.desc()).offset((page - 1) * limit).limit(limit)
    )
    return APIResponse.paginated([serialize_file(item) for item in result.scalars().all()], total or 0, page, limit)


@router.get("/{file_id}")
async def get_file(file_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UploadedFile).where(UploadedFile.id == file_id, UploadedFile.user_id == current_user.id)
    )
    uploaded = result.scalar_one_or_none()
    if not uploaded:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return APIResponse.success(serialize_file(uploaded))
