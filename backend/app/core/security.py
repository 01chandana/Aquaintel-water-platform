"""JWT, password hashing and MFA utilities (spec Ch. 17.2).

* Passwords: Argon2id (Table 6.1 ``password_hash``)
* API keys: bcrypt hash, never logged (Ch. 17.4.3)
* Access token: 60 min HS256; refresh token: 7 days, rotated on every use (Ch. 17.2.1)
* Revocation: ``jti`` blacklist in Redis
* MFA: TOTP RFC 6238 via ``pyotp`` + one-time backup codes
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError

_ph = PasswordHasher()

ACCESS = "access"
REFRESH = "refresh"
MFA_CHALLENGE = "mfa"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def create_token(
    *,
    subject: str,
    token_type: str,
    role: str | None = None,
    permissions: list[str] | None = None,
    asset_scopes: list[str] | None = None,
    expires_delta: timedelta | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = (
            timedelta(days=settings.jwt_refresh_expiry_days)
            if token_type == REFRESH
            else timedelta(minutes=5 if token_type == MFA_CHALLENGE else settings.jwt_expiry_minutes)
        )
    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": f"tok_{uuid.uuid4().hex}",
    }
    if token_type == ACCESS:
        claims.update(role=role, permissions=permissions or [], asset_scopes=asset_scopes or [])
    if extra:
        claims.update(extra)
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, claims


def decode_token(token: str, expected_type: str = ACCESS) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired token") from exc
    if claims.get("type") != expected_type:
        raise AuthenticationError(f"Expected {expected_type} token")
    return claims


# ---- MFA (Ch. 17.2.2) -------------------------------------------------------------------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="AquaIntel")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_backup_codes(n: int = 8) -> tuple[list[str], list[str]]:
    plain = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]
    return plain, [sha256(c) for c in plain]


# ---- API keys (Ch. 17.2.3) --------------------------------------------------------------
API_KEY_PREFIX = "aq_"


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(plaintext, lookup_prefix, bcrypt_hash)``. Plaintext is shown once."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = raw[:11]
    return raw, prefix, bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_api_key(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def reset_token() -> str:
    return secrets.token_urlsafe(32)
