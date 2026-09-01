from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from threading import Lock
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.household import (
    BOOTSTRAP_HOUSEHOLD_ID,
    RequestPrincipal,
    principal_scope,
)
from app.db.household_scope import INCLUDE_ALL_HOUSEHOLDS
from app.models.auth import AuthSession, Household, SecurityAuditEvent, User, UserRole
from app.models.mixins import utc_now

LOGIN_PATTERN = re.compile(r"^[a-z0-9._-]{3,100}$")
SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32


class AuthenticationError(PermissionError):
    pass


class LoginRateLimitError(AuthenticationError):
    pass


class BootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class IssuedSession:
    principal: RequestPrincipal
    login: str
    role: str
    session_token: str
    csrf_token: str


class LoginRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, *, now: datetime, limit: int, window_seconds: int) -> None:
        cutoff = now - timedelta(seconds=window_seconds)
        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= limit:
                raise LoginRateLimitError("authentication temporarily unavailable")
            attempts.append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


login_rate_limiter = LoginRateLimiter()


@lru_cache
def get_password_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=2,
        memory_cost=19 * 1024,
        parallelism=1,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


@lru_cache
def _dummy_password_hash() -> str:
    return get_password_hasher().hash("not-a-real-household-password")


def normalize_login(value: str) -> str:
    normalized = value.strip().casefold()
    if not LOGIN_PATTERN.fullmatch(normalized):
        raise AuthenticationError("invalid credentials")
    return normalized


def validate_new_password(value: str) -> None:
    if len(value) < 12 or len(value) > 1024:
        raise AuthenticationError("new password must contain 12 to 1024 characters")


def authenticate_and_create_session(
    session: Session,
    *,
    login: str,
    password: str,
    settings: Settings,
    client_fingerprint: str | None,
) -> IssuedSession:
    normalized_login = normalize_login(login)
    user = session.scalar(
        select(User)
        .join(Household)
        .where(
            User.normalized_login == normalized_login,
            User.is_active.is_(True),
            Household.is_active.is_(True),
        )
        .execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    )
    password_hash = user.password_hash if user is not None else _dummy_password_hash()
    if not _verify_password(password_hash, password) or user is None:
        _record_audit(
            session,
            household_id=user.household_id if user is not None else BOOTSTRAP_HOUSEHOLD_ID,
            user_id=user.id if user is not None else None,
            event_type="login",
            outcome="failed",
            detail_code="invalid_credentials",
        )
        session.commit()
        raise AuthenticationError("invalid credentials")

    now = utc_now()
    session_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
    auth_session = AuthSession(
        household_id=user.household_id,
        user_id=user.id,
        token_digest=_digest(session_token),
        csrf_digest=_digest(csrf_token),
        issued_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(seconds=settings.auth_session_idle_seconds),
        absolute_expires_at=now + timedelta(seconds=settings.auth_session_absolute_seconds),
        client_fingerprint=client_fingerprint,
    )
    principal = RequestPrincipal(
        household_id=user.household_id,
        user_id=user.id,
        role=user.role,
        auth_session_id=auth_session.id,
    )
    with principal_scope(principal):
        session.add(auth_session)
        session.flush()
        principal = RequestPrincipal(
            household_id=user.household_id,
            user_id=user.id,
            role=user.role,
            auth_session_id=auth_session.id,
        )
        _record_audit(
            session,
            household_id=user.household_id,
            user_id=user.id,
            auth_session_id=auth_session.id,
            event_type="login",
            outcome="succeeded",
        )
        session.commit()
    return IssuedSession(
        principal=principal,
        login=user.normalized_login,
        role=user.role,
        session_token=session_token,
        csrf_token=csrf_token,
    )


def load_session_principal(
    session: Session,
    *,
    session_token: str,
    settings: Settings,
    rotate_csrf: bool = False,
) -> tuple[RequestPrincipal, User, AuthSession, str | None]:
    now = utc_now()
    auth_session = session.scalar(
        select(AuthSession)
        .where(AuthSession.token_digest == _digest(session_token))
        .options(joinedload(AuthSession.user).joinedload(User.household))
        .execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    )
    if auth_session is None or auth_session.revoked_at is not None:
        raise AuthenticationError("authentication required")
    user = auth_session.user
    if (
        _as_utc(auth_session.idle_expires_at) <= now
        or _as_utc(auth_session.absolute_expires_at) <= now
        or not user.is_active
        or not user.household.is_active
    ):
        if auth_session.revoked_at is None:
            with principal_scope(_principal(user, auth_session)):
                auth_session.revoked_at = now
                session.commit()
        raise AuthenticationError("authentication required")

    principal = _principal(user, auth_session)
    csrf_token: str | None = None
    with principal_scope(principal):
        if now - _as_utc(auth_session.last_seen_at) >= timedelta(
            seconds=settings.auth_session_touch_interval_seconds
        ):
            auth_session.last_seen_at = now
            auth_session.idle_expires_at = min(
                now + timedelta(seconds=settings.auth_session_idle_seconds),
                _as_utc(auth_session.absolute_expires_at),
            )
        if rotate_csrf:
            csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
            auth_session.csrf_digest = _digest(csrf_token)
        session.commit()
    return principal, user, auth_session, csrf_token


def verify_csrf_token(auth_session: AuthSession, supplied_token: str | None) -> None:
    if supplied_token is None or not hmac.compare_digest(
        auth_session.csrf_digest,
        _digest(supplied_token),
    ):
        raise AuthenticationError("request verification failed")


def revoke_session(
    session: Session, auth_session: AuthSession, principal: RequestPrincipal
) -> None:
    with principal_scope(principal):
        auth_session.revoked_at = utc_now()
        _record_audit(
            session,
            household_id=principal.household_id,
            user_id=principal.user_id,
            auth_session_id=auth_session.id,
            event_type="logout",
            outcome="succeeded",
        )
        session.commit()


def change_password(
    session: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    principal: RequestPrincipal,
) -> None:
    validate_new_password(new_password)
    if not _verify_password(user.password_hash, current_password):
        raise AuthenticationError("invalid credentials")
    now = utc_now()
    with principal_scope(principal):
        user.password_hash = get_password_hasher().hash(new_password)
        user.password_changed_at = now
        session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        _record_audit(
            session,
            household_id=user.household_id,
            user_id=user.id,
            auth_session_id=principal.auth_session_id,
            event_type="password_change",
            outcome="succeeded",
        )
        session.commit()


def create_bootstrap_owner(
    session: Session,
    *,
    login: str,
    password: str,
    household_name: str,
) -> User:
    normalized_login = normalize_login(login)
    validate_new_password(password)
    existing = session.scalar(
        select(User.id).limit(1).execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    )
    if existing is not None:
        raise BootstrapError("an owner already exists")
    household = session.scalar(
        select(Household)
        .where(Household.id == BOOTSTRAP_HOUSEHOLD_ID)
        .execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    )
    if household is None:
        household = Household(
            id=BOOTSTRAP_HOUSEHOLD_ID,
            display_name=household_name.strip() or "Home household",
            is_active=True,
        )
        session.add(household)
    else:
        household.display_name = household_name.strip() or household.display_name
    now = utc_now()
    user = User(
        household_id=household.id,
        normalized_login=normalized_login,
        password_hash=get_password_hasher().hash(password),
        role=UserRole.OWNER,
        is_active=True,
        password_changed_at=now,
    )
    local_owner = RequestPrincipal(household.id, None, UserRole.OWNER, None, is_local_mode=True)
    with principal_scope(local_owner):
        session.add(user)
        session.flush()
        _record_audit(
            session,
            household_id=household.id,
            user_id=user.id,
            event_type="owner_bootstrap",
            outcome="succeeded",
        )
        session.commit()
    return user


def reset_owner_password(session: Session, *, login: str, new_password: str) -> None:
    normalized_login = normalize_login(login)
    validate_new_password(new_password)
    user = session.scalar(
        select(User)
        .where(User.normalized_login == normalized_login, User.role == UserRole.OWNER)
        .execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    )
    if user is None:
        raise BootstrapError("owner not found")
    now = utc_now()
    principal = RequestPrincipal(user.household_id, user.id, user.role, None, is_local_mode=True)
    with principal_scope(principal):
        user.password_hash = get_password_hasher().hash(new_password)
        user.password_changed_at = now
        session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        _record_audit(
            session,
            household_id=user.household_id,
            user_id=user.id,
            event_type="password_recovery",
            outcome="succeeded",
        )
        session.commit()


def client_fingerprint(value: str | None) -> str | None:
    return _digest(value) if value else None


def _principal(user: User, auth_session: AuthSession) -> RequestPrincipal:
    return RequestPrincipal(
        household_id=user.household_id,
        user_id=user.id,
        role=user.role,
        auth_session_id=auth_session.id,
    )


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return get_password_hasher().verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_audit(
    session: Session,
    *,
    household_id: UUID,
    event_type: str,
    outcome: str,
    user_id: UUID | None = None,
    auth_session_id: UUID | None = None,
    detail_code: str | None = None,
) -> None:
    session.add(
        SecurityAuditEvent(
            household_id=household_id,
            user_id=user_id,
            auth_session_id=auth_session_id,
            event_type=event_type,
            outcome=outcome,
            detail_code=detail_code,
            created_at=datetime.now(UTC),
        )
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
