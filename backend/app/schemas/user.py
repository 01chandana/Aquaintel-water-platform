"""Auth and user management schemas (Tables 7.1, 7.2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.permissions import ROLE_PERMISSIONS
from app.schemas.common import APIModel, ORMModel, Secret

PASSWORD_MIN = 10


def _password_policy(value: str) -> str:
    if len(value) < PASSWORD_MIN or value.lower() == value or not any(c.isdigit() for c in value):
        raise ValueError(f"Password must be >= {PASSWORD_MIN} chars and include an uppercase letter and a digit")
    return value


class LoginRequest(APIModel):
    email: EmailStr
    password: Secret = Field(min_length=1, max_length=256)


class TokenPair(APIModel):
    access_token: str
    refresh_token: Secret
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(APIModel):
    mfa_required: bool = False
    mfa_token: str | None = None
    tokens: TokenPair | None = None
    user: UserOut | None = None


class RefreshRequest(APIModel):
    refresh_token: Secret


class LogoutRequest(APIModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(APIModel):
    email: EmailStr


class ResetPasswordRequest(APIModel):
    token: Secret
    new_password: Secret = Field(max_length=128)

    _v = field_validator("new_password")(_password_policy)


class MfaSetupResponse(APIModel):
    secret: str
    otpauth_uri: str
    backup_codes: list[str]


class MfaVerifyRequest(APIModel):
    code: str = Field(min_length=6, max_length=12)


class RoleOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str]


class UserOut(ORMModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: str
    is_active: bool
    mfa_enabled: bool
    asset_scopes: list[str] = []
    phone: str | None = Field(default=None, max_length=32)
    last_login: datetime | None = None
    created_at: datetime

    @field_validator("role", mode="before")
    @classmethod
    def _role_name(cls, v: object) -> object:
        return getattr(v, "name", v)


class UserCreate(APIModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=150)
    password: Secret = Field(max_length=128)
    role: str = "operator"
    asset_scopes: list[str] = []
    phone: str | None = Field(default=None, max_length=32)

    _v = field_validator("password")(_password_policy)

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ROLE_PERMISSIONS:
            raise ValueError(f"role must be one of {sorted(ROLE_PERMISSIONS)}")
        return v


class UserUpdate(APIModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    is_active: bool | None = None
    asset_scopes: list[str] | None = None
    phone: str | None = Field(default=None, max_length=32)


class SelfUpdate(APIModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=32)
    current_password: Secret | None = Field(default=None, max_length=256)
    new_password: Secret | None = Field(default=None, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v: str | None) -> str | None:
        return _password_policy(v) if v else v


class RoleAssign(APIModel):
    role: str

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ROLE_PERMISSIONS:
            raise ValueError(f"role must be one of {sorted(ROLE_PERMISSIONS)}")
        return v


class PermissionsOut(APIModel):
    user_id: uuid.UUID
    role: str
    permissions: list[str]
    asset_scopes: list[str]


class ApiKeyCreate(APIModel):
    name: str = Field(min_length=3, max_length=120)
    permissions: list[str] = ["telemetry:ingest"]
    asset_scopes: list[str] = []
    expires_in_days: int = Field(90, ge=1, le=365)  # Ch. 17.2.3: rotate every 90 days


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    permissions: list[str]
    asset_scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked: bool
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    api_key: str  # plaintext, returned exactly once


LoginResponse.model_rebuild()
