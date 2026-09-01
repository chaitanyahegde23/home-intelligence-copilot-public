from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.household import LOCAL_PRINCIPAL, RequestPrincipal
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.db.session import get_db
from app.services.authentication import (
    AuthenticationError,
    load_session_principal,
    verify_csrf_token,
)

SESSION_COOKIE_NAME = "__Host-hic_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_request_principal(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> RequestPrincipal:
    if settings.auth_mode == "local":
        session.info[SESSION_HOUSEHOLD_KEY] = LOCAL_PRINCIPAL.household_id
        return LOCAL_PRINCIPAL
    if session_token is None:
        raise _unauthorized()
    try:
        principal, _, _, _ = load_session_principal(
            session,
            session_token=session_token,
            settings=settings,
        )
    except AuthenticationError as exc:
        raise _unauthorized() from exc
    session.info[SESSION_HOUSEHOLD_KEY] = principal.household_id
    return principal


def enforce_csrf(
    request: Request,
    principal: Annotated[RequestPrincipal, Depends(require_request_principal)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    csrf_token: Annotated[str | None, Header(alias=CSRF_HEADER_NAME)] = None,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    del principal
    if settings.auth_mode == "local" or request.method in SAFE_METHODS:
        return
    _validate_origin(request, settings)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise _forbidden()
    if session_token is None:
        raise _unauthorized()
    try:
        _, _, auth_session, _ = load_session_principal(
            session,
            session_token=session_token,
            settings=settings,
        )
        verify_csrf_token(auth_session, csrf_token)
    except AuthenticationError as exc:
        raise _forbidden() from exc


def _validate_origin(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.auth_allowed_origin:
        raise _forbidden()
    if request.headers.get("host") not in settings.auth_allowed_hosts:
        raise _forbidden()


def validate_login_origin(request: Request, settings: Settings) -> None:
    if settings.auth_mode == "secure":
        _validate_origin(request, settings)
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise _forbidden()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="request verification failed",
    )
