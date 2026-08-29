from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import logging
import os
import secrets
import smtplib

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import PasswordResetToken, User
from services.auth_service import keyed_hash


logger = logging.getLogger(__name__)
GENERIC_RESET_MESSAGE = "If an account exists for that email, a password reset link has been sent."


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalized_email(email: str) -> str:
    return email.strip().lower()


def _reset_url(token: str) -> str:
    base = os.getenv("APP_PUBLIC_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    return f"{base}/app/pages/reset-password.html?token={token}"


@dataclass(frozen=True)
class PasswordResetDelivery:
    email: str
    reset_url: str


def request_password_reset(db: Session, email: str, request_ip: str | None) -> PasswordResetDelivery | None:
    now = _utcnow()
    window_start = now - timedelta(minutes=_positive_int("PASSWORD_RESET_WINDOW_MINUTES", 60))
    normalized_email = _normalized_email(email)
    email_hash = keyed_hash(f"email:{normalized_email}")
    ip_hash = keyed_hash(f"ip:{request_ip or 'unknown'}")

    email_count = db.query(func.count(PasswordResetToken.id)).filter(
        PasswordResetToken.email_hash == email_hash,
        PasswordResetToken.created_at >= window_start,
    ).scalar() or 0
    ip_count = db.query(func.count(PasswordResetToken.id)).filter(
        PasswordResetToken.request_ip_hash == ip_hash,
        PasswordResetToken.created_at >= window_start,
    ).scalar() or 0

    if email_count >= _positive_int("PASSWORD_RESET_EMAIL_LIMIT", 3):
        return None
    if ip_count >= _positive_int("PASSWORD_RESET_IP_LIMIT", 10):
        return None

    users = db.query(User).filter(func.lower(User.email) == normalized_email).limit(2).all()
    user = users[0] if len(users) == 1 and users[0].is_active else None
    token = secrets.token_urlsafe(48)
    db.add(
        PasswordResetToken(
            user_id=user.id if user else None,
            email_hash=email_hash,
            request_ip_hash=ip_hash,
            token_hash=_token_hash(token),
            expires_at=now + timedelta(minutes=_positive_int("PASSWORD_RESET_TOKEN_MINUTES", 30)),
        )
    )

    # Keep rate-limit records for one day, then remove them opportunistically.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.created_at < now - timedelta(days=1),
    ).delete(synchronize_session=False)
    db.commit()

    if not user:
        return None
    return PasswordResetDelivery(email=user.email, reset_url=_reset_url(token))


def consume_password_reset(db: Session, token: str, new_password_hash: str) -> User | None:
    now = _utcnow()
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == _token_hash(token),
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now,
        PasswordResetToken.user_id.is_not(None),
    ).with_for_update().first()
    if not reset:
        return None

    user = db.query(User).filter(User.id == reset.user_id, User.is_active.is_(True)).first()
    if not user:
        return None

    user.hashed_password = new_password_hash
    user.password_changed_at = now
    user.must_change_password = False
    user.session_version = (user.session_version or 1) + 1
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    return user


def send_password_reset_email(delivery: PasswordResetDelivery) -> None:
    mode = os.getenv("PASSWORD_RESET_DELIVERY", "console").strip().lower()
    if mode == "console":
        logger.warning("LOCAL PASSWORD RESET for %s: %s", delivery.email, delivery.reset_url)
        return
    if mode != "smtp":
        logger.error("Password reset delivery is disabled; set PASSWORD_RESET_DELIVERY to console or smtp")
        return

    host = os.getenv("SMTP_HOST", "").strip()
    from_email = os.getenv("SMTP_FROM_EMAIL", "").strip()
    if not host or not from_email:
        logger.error("SMTP_HOST and SMTP_FROM_EMAIL are required for password reset email")
        return

    port = _positive_int("SMTP_PORT", 587)
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}

    message = EmailMessage()
    message["Subject"] = "Reset your MISRA EDU password"
    message["From"] = from_email
    message["To"] = delivery.email
    message.set_content(
        "A password reset was requested for your MISRA EDU instructor account.\n\n"
        f"Reset your password: {delivery.reset_url}\n\n"
        "This link expires shortly and can be used only once. If you did not request it, ignore this email."
    )

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except Exception:
        logger.exception("Could not deliver password reset email to %s", delivery.email)
