from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.security import create_access_token, create_refresh_token, get_password_hash, verify_password, verify_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenRefresh, UserCreate, UserLogin, UserOut
from app.utils.response import APIResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def serialize_user(user: User) -> dict:
    return UserOut(
        id=str(user.id),
        name=user.name,
        email=user.email,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        is_active=user.is_active,
    ).model_dump()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=get_password_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return APIResponse.success(serialize_user(user), "User registered", status.HTTP_201_CREATED)


@router.post("/login")
async def login(payload: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    token_data = {"sub": str(user.id)}
    data = {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "user": serialize_user(user),
    }
    return APIResponse.success(data, "Login successful")


@router.post("/refresh")
async def refresh_token(payload: TokenRefresh):
    decoded = verify_token(payload.refresh_token, "refresh")
    subject = decoded.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return APIResponse.success({"access_token": create_access_token({"sub": subject}), "token_type": "bearer"})


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return APIResponse.success(serialize_user(current_user))
