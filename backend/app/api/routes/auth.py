from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import (
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    validate_login_origin,
)
from app.core.config import Settings, get_settings
from app.core.household import principal_scope
from app.db.session import get_db
from app.schemas.auth import AuthSessionResponse, LoginRequest, PasswordChangeRequest
from app.services.authentication import (
    AuthenticationError,
    LoginRateLimitError,
    authenticate_and_create_session,
    change_password,
    client_fingerprint,
    load_session_principal,
    login_rate_limiter,
    revoke_session,
    verify_csrf_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/session", response_model=AuthSessionResponse)
def get_auth_session(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AuthSessionResponse:
    if settings.auth_mode == "local":
        return AuthSessionResponse(
            mode="local", authenticated=True, login=None, role="owner", csrf_token=None
        )
    if session_token is None:
        raise _unauthorized()
    try:
        _, user, _, csrf_token = load_session_principal(
            session,
            session_token=session_token,
            settings=settings,
            rotate_csrf=True,
        )
    except AuthenticationError as exc:
        raise _unauthorized() from exc
    return AuthSessionResponse(
        mode="secure",
        authenticated=True,
        login=user.normalized_login,
        role=user.role,
        csrf_token=csrf_token,
    )


@router.post("/login", response_model=AuthSessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthSessionResponse:
    if settings.auth_mode != "secure":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    validate_login_origin(request, settings)
    key = f"{request.client.host if request.client else 'unknown'}:{payload.login.casefold()}"
    try:
        login_rate_limiter.check(
            key,
            now=datetime.now(UTC),
            limit=settings.auth_login_attempt_limit,
            window_seconds=settings.auth_login_window_seconds,
        )
        issued = authenticate_and_create_session(
            session,
            login=payload.login,
            password=payload.password,
            settings=settings,
            client_fingerprint=client_fingerprint(request.client.host if request.client else None),
        )
    except LoginRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="authentication temporarily unavailable",
            headers={"Retry-After": str(settings.auth_login_window_seconds)},
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        ) from exc
    login_rate_limiter.clear(key)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=issued.session_token,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=settings.auth_session_absolute_seconds,
    )
    return AuthSessionResponse(
        mode="secure",
        authenticated=True,
        login=issued.login,
        role=issued.role,
        csrf_token=issued.csrf_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    if settings.auth_mode == "local":
        return
    validate_login_origin(request, settings)
    if session_token is None:
        raise _unauthorized()
    try:
        principal, _, auth_session, _ = load_session_principal(
            session, session_token=session_token, settings=settings
        )
        verify_csrf_token(auth_session, request.headers.get(CSRF_HEADER_NAME))
        revoke_session(session, auth_session, principal)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="request verification failed",
        ) from exc
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def update_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    if settings.auth_mode != "secure" or session_token is None:
        raise _unauthorized()
    validate_login_origin(request, settings)
    try:
        principal, user, auth_session, _ = load_session_principal(
            session, session_token=session_token, settings=settings
        )
        verify_csrf_token(auth_session, request.headers.get(CSRF_HEADER_NAME))
        with principal_scope(principal):
            change_password(
                session,
                user=user,
                current_password=payload.current_password,
                new_password=payload.new_password,
                principal=principal,
            )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
