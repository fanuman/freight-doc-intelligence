"""Request/response shapes for the auth endpoints.

Pydantic schemas describe what crosses the HTTP boundary. They are separate
from the database models on purpose: a response must never accidentally expose
password_hash just because the column exists. (Django REST: serializers.)
"""
from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    company_name: str = Field(max_length=200)
    email: EmailStr
    # 12+ characters follows current NIST guidance (length beats complexity rules).
    # The upper bound stops someone submitting a 10 MB "password" to burn CPU in argon2.
    password: str = Field(min_length=12, max_length=128)

    @field_validator("company_name")
    @classmethod
    def company_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
