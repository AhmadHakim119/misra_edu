from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass


SESSION_COOKIE = "misra_session"
CSRF_COOKIE = "misra_csrf"
SESSION_SECONDS = 8 * 60 * 60
REMEMBERED_SESSION_SECONDS = 30 * 24 * 60 * 60
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


@dataclass(frozen=True)
class SessionClaims:
    user_id: str
    expires_at: int
    session_version: int


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _auth_secret() -> bytes:
    value = os.getenv("AUTH_SECRET")
    if not value or value.startswith("replace-with-") or len(value) < 32:
        raise RuntimeError("AUTH_SECRET must be configured with at least 32 characters")
    return value.encode("utf-8")


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(digest, _b64decode(expected))
    except (TypeError, ValueError):
        return False


def create_session_token(user_id: str, remember: bool = False, session_version: int = 1) -> tuple[str, int]:
    max_age = REMEMBERED_SESSION_SECONDS if remember else SESSION_SECONDS
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + max_age,
        "ver": session_version,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64encode(hmac.new(_auth_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}", max_age


def read_session_token(token: str | None) -> SessionClaims | None:
    if not token:
        return None
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64encode(hmac.new(_auth_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64decode(encoded))
        expires_at = int(payload["exp"])
        if expires_at <= int(time.time()):
            return None
        return SessionClaims(
            user_id=str(payload["sub"]),
            expires_at=expires_at,
            session_version=int(payload["ver"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def keyed_hash(value: str) -> str:
    return hmac.new(_auth_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
