"""Authentication: login, MFA challenge, refresh rotation, logout and password reset (Ch. 17.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheBackend
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ValidationError
from app.core.logging import get_logger
from app.core.security import (
    ACCESS,
    MFA_CHALLENGE,
    REFRESH,
    create_token,
    decode_token,
    generate_backup_codes,
    hash_password,
    needs_rehash,
    new_totp_secret,
    reset_token,
    sha256,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import LoginResponse, MfaSetupResponse, TokenPair, UserOut
from app.services.audit_service import AuditService
from app.services.notification_service import send_email

log = get_logger(__name__)


class AuthService:
    def __init__(self, repo: UserRepository, cache: CacheBackend) -> None:
        self.repo = repo
        self.cache = cache
        self.session: AsyncSession = repo.session
        self.audit = AuditService(repo.session)

    # ---- token helpers -------------------------------------------------------------------
    async def _issue(self, user: User) -> TokenPair:
        settings = get_settings()
        access, _ = create_token(
            subject=str(user.id), token_type=ACCESS, role=user.role.name,
            permissions=sorted(user.role.permissions), asset_scopes=list(user.asset_scopes or []),
        )
        refresh, rclaims = create_token(subject=str(user.id), token_type=REFRESH)
        ttl = settings.jwt_refresh_expiry_days * 86400
        await self.cache.set_json(f"refresh:{user.id}:{rclaims['jti']}", {"user_id": str(user.id)}, ttl)
        return TokenPair(access_token=access, refresh_token=refresh, expires_in=settings.jwt_expiry_minutes * 60)

    async def validate_token(self, token: str) -> User | None:
        """Name kept from spec Listing 9.2."""
        claims = decode_token(token, ACCESS)
        if await self.cache.exists(f"blacklist:{claims['jti']}"):
            return None
        return await self.repo.get(uuid.UUID(claims["sub"]))

    # ---- login ---------------------------------------------------------------------------
    async def login(self, email: str, password: str) -> LoginResponse:
        settings = get_settings()
        user = await self.repo.get_by_email(email)
        now = datetime.now(UTC)
        if user and user.locked_until and user.locked_until > now:
            raise AuthenticationError("Account temporarily locked after repeated failures")
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            if user:
                user.failed_login_count += 1
                if user.failed_login_count >= settings.login_lockout_threshold:
                    user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                    await self.audit.record("auth.lockout", "user", user.id, details={"email": email})
                await self.session.commit()
            log.warning("login_failed", email=email)
            raise AuthenticationError("Invalid email or password")

        user.failed_login_count = 0
        user.locked_until = None
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        if user.mfa_enabled:
            mfa_token, _ = create_token(subject=str(user.id), token_type=MFA_CHALLENGE)
            await self.session.commit()
            return LoginResponse(mfa_required=True, mfa_token=mfa_token)

        user.last_login = now
        await self.audit.record("auth.login", "user", user.id, principal=_P(user))
        await self.session.commit()
        return LoginResponse(tokens=await self._issue(user), user=UserOut.model_validate(user))

    async def verify_mfa_login(self, mfa_token: str, code: str) -> LoginResponse:
        claims = decode_token(mfa_token, MFA_CHALLENGE)
        user = await self.repo.get(uuid.UUID(claims["sub"]))
        if not user or not user.mfa_secret:
            raise AuthenticationError("MFA not configured")
        if not self._check_code(user, code):
            raise AuthenticationError("Invalid MFA code")
        user.last_login = datetime.now(UTC)
        await self.audit.record("auth.login_mfa", "user", user.id, principal=_P(user))
        await self.session.commit()
        return LoginResponse(tokens=await self._issue(user), user=UserOut.model_validate(user))

    def _check_code(self, user: User, code: str) -> bool:
        if user.mfa_secret and verify_totp(user.mfa_secret, code):
            return True
        hashed = sha256(code.strip())
        if user.mfa_backup_codes and hashed in user.mfa_backup_codes:
            user.mfa_backup_codes = [c for c in user.mfa_backup_codes if c != hashed]  # one-time use
            return True
        return False

    # ---- refresh rotation / logout -------------------------------------------------------
    async def refresh(self, refresh_token: str) -> TokenPair:
        claims = decode_token(refresh_token, REFRESH)
        key = f"refresh:{claims['sub']}:{claims['jti']}"
        stored = await self.cache.get_json(key)
        if not stored:
            # Re-use of a rotated token signals theft: revoke every session of that user.
            await self.cache.delete_pattern(f"refresh:{claims['sub']}:*")
            raise AuthenticationError("Refresh token invalid or already used")
        await self.cache.delete(key)  # rotation: each refresh token is single-use
        user = await self.repo.get(uuid.UUID(claims["sub"]))
        if not user or not user.is_active:
            raise AuthenticationError("User inactive")
        return await self._issue(user)

    async def logout(self, access_claims: dict[str, Any], refresh_token: str | None) -> None:
        ttl = max(1, int(access_claims["exp"] - datetime.now(UTC).timestamp()))
        await self.cache.set_json(f"blacklist:{access_claims['jti']}", True, ttl)
        if refresh_token:
            try:
                rclaims = decode_token(refresh_token, REFRESH)
                await self.cache.delete(f"refresh:{rclaims['sub']}:{rclaims['jti']}")
            except AuthenticationError:
                pass

    # ---- password reset ------------------------------------------------------------------
    async def forgot_password(self, email: str) -> None:
        user = await self.repo.get_by_email(email)
        if not user:
            return  # do not reveal whether an account exists
        token = reset_token()
        await self.cache.set_json(f"pwreset:{sha256(token)}", {"user_id": str(user.id)}, 1800)
        await send_email(user.email, "AquaIntel password reset",
                         f"Use this token within 30 minutes to reset your password: {token}")
        await self.audit.record("auth.password_reset_requested", "user", user.id)
        await self.session.commit()

    async def reset_password(self, token: str, new_password: str) -> None:
        key = f"pwreset:{sha256(token)}"
        stored = await self.cache.get_json(key)
        if not stored:
            raise ValidationError("Reset token invalid or expired")
        user = await self.repo.get_or_404(uuid.UUID(stored["user_id"]), "User")
        user.password_hash = hash_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        await self.cache.delete(key)
        await self.audit.record("auth.password_reset", "user", user.id)
        await self.session.commit()

    # ---- MFA enrolment -------------------------------------------------------------------
    async def mfa_setup(self, user: User) -> MfaSetupResponse:
        secret = new_totp_secret()
        plain, hashed = generate_backup_codes()
        await self.cache.set_json(f"mfa_pending:{user.id}", {"secret": secret, "codes": hashed}, 900)
        return MfaSetupResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email), backup_codes=plain)

    async def mfa_confirm(self, user: User, code: str) -> None:
        pending = await self.cache.get_json(f"mfa_pending:{user.id}")
        if not pending:
            raise ValidationError("Start MFA setup first")
        if not verify_totp(pending["secret"], code):
            raise AuthenticationError("Invalid MFA code")
        user.mfa_secret = pending["secret"]
        user.mfa_backup_codes = pending["codes"]
        user.mfa_enabled = True
        await self.cache.delete(f"mfa_pending:{user.id}")
        await self.audit.record("auth.mfa_enabled", "user", user.id, principal=_P(user))
        await self.session.commit()


class _P:
    """Minimal principal adapter for audit records written before a Principal exists."""

    def __init__(self, user: User) -> None:
        self.user_id = user.id
        self.name = user.email
