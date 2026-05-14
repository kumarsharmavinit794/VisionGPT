from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import json
from typing import Optional
from fastapi import HTTPException, status
from app.core.config import settings

try:
    from jose import JWTError, jwt
except ModuleNotFoundError:
    JWTError = ValueError
    jwt = None

try:
    from passlib.context import CryptContext
except ModuleNotFoundError:
    CryptContext = None

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") if CryptContext else None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    if pwd_context is None:
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    if pwd_context is None:
        return hashlib.sha256(password.encode()).hexdigest()
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    if jwt is None:
        encoded_jwt = _fallback_encode(to_encode)
    else:
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    if jwt is None:
        encoded_jwt = _fallback_encode(to_encode)
    else:
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> dict:
    """Verify and decode JWT token."""
    try:
        payload = _fallback_decode(token) if jwt is None else jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != token_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _fallback_encode(payload: dict) -> str:
    serializable = payload.copy()
    if isinstance(serializable.get("exp"), datetime):
        serializable["exp"] = int(serializable["exp"].timestamp())
    body = base64.urlsafe_b64encode(json.dumps(serializable).encode()).decode().rstrip("=")
    signature = hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _fallback_decode(token: str) -> dict:
    body, signature = token.rsplit(".", 1)
    expected = hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid token signature")
    padding = "=" * (-len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode((body + padding).encode()).decode())
    if payload.get("exp") and int(payload["exp"]) < int(datetime.utcnow().timestamp()):
        raise ValueError("Token expired")
    return payload
