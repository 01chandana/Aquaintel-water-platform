"""Authentication endpoints #1-7 (Table 7.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import DB, Cache, CurrentUser, bearer
from app.core.exceptions import AuthenticationError
from app.core.responses import ok
from app.core.security import ACCESS, MFA_CHALLENGE, decode_token
from app.middleware.rate_limit import login_rate_limit
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MfaVerifyRequest,
    RefreshRequest,
    ResetPasswordRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _svc(db: DB, cache: Cache) -> AuthService:
    return AuthService(UserRepository(db), cache)


@router.post("/login", dependencies=[Depends(login_rate_limit)], summary="#1 User login")
async def login(body: LoginRequest, db: DB, cache: Cache) -> dict:
    return ok(await _svc(db, cache).login(body.email, body.password))


@router.post("/refresh", dependencies=[Depends(login_rate_limit)], summary="#2 Refresh access token (rotating)")
async def refresh(body: RefreshRequest, db: DB, cache: Cache) -> dict:
    return ok(await _svc(db, cache).refresh(body.refresh_token))


@router.post("/logout", summary="#3 Invalidate session")
async def logout(body: LogoutRequest, db: DB, cache: Cache,
                 credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None:
        raise AuthenticationError("Missing bearer token")
    claims = decode_token(credentials.credentials, ACCESS)
    await _svc(db, cache).logout(claims, body.refresh_token)
    return ok({"message": "Logged out"})


@router.post("/forgot-password", dependencies=[Depends(login_rate_limit)], summary="#4 Request password reset")
async def forgot_password(body: ForgotPasswordRequest, db: DB, cache: Cache) -> dict:
    await _svc(db, cache).forgot_password(body.email)
    return ok({"message": "If the account exists, a reset link has been sent"})


@router.post("/reset-password", dependencies=[Depends(login_rate_limit)], summary="#5 Reset password")
async def reset_password(body: ResetPasswordRequest, db: DB, cache: Cache) -> dict:
    await _svc(db, cache).reset_password(body.token, body.new_password)
    return ok({"message": "Password updated"})


@router.post("/mfa/setup", summary="#6 Configure MFA (TOTP)")
async def mfa_setup(principal: CurrentUser, db: DB, cache: Cache) -> dict:
    assert principal.user is not None
    return ok(await _svc(db, cache).mfa_setup(principal.user))


@router.post("/mfa/verify", summary="#7 Verify MFA code",
             description="With an **MFA challenge token** (from login) as Bearer: completes login and returns tokens. "
                         "With an **access token**: confirms MFA enrolment started by /auth/mfa/setup.")
async def mfa_verify(body: MfaVerifyRequest, db: DB, cache: Cache,
                     credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None:
        raise AuthenticationError("Missing bearer token")
    svc = _svc(db, cache)
    try:
        decode_token(credentials.credentials, MFA_CHALLENGE)
        return ok(await svc.verify_mfa_login(credentials.credentials, body.code))
    except AuthenticationError as exc:
        if "Expected mfa token" not in str(exc):
            raise
    user = await svc.validate_token(credentials.credentials)
    if user is None:
        raise AuthenticationError("Invalid or expired token")
    await svc.mfa_confirm(user, body.code)
    return ok({"mfa_enabled": True})
