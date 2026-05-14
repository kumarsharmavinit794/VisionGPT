import re
from pydantic import BaseModel, Field, field_validator

try:
    import email_validator  # noqa: F401
    from pydantic import EmailStr
except ModuleNotFoundError:
    EmailStr = str


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name", "email", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not re.search(r"[A-Z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must contain at least one uppercase letter and one number")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class TokenRefresh(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    is_active: bool
