from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.household_scope import INCLUDE_ALL_HOUSEHOLDS
from app.db.session import get_db
from app.main import app
from app.models import AuthSession, SecurityAuditEvent
from app.services.authentication import (
    create_bootstrap_owner,
    login_rate_limiter,
)

ORIGIN_HEADERS = {"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"}
OWNER_PASSWORD = "synthetic-owner-password"


@pytest.fixture
def secure_client() -> Iterator[tuple[TestClient, Session, Settings]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    database_session = Session(engine)
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        auth_mode="secure",
        auth_allowed_origin="https://testserver",
        auth_allowed_hosts=["testserver"],
        auth_session_idle_seconds=300,
        auth_session_absolute_seconds=600,
        auth_session_touch_interval_seconds=0,
        auth_login_attempt_limit=2,
        auth_login_window_seconds=60,
    )
    create_bootstrap_owner(
        database_session,
        login="owner",
        password=OWNER_PASSWORD,
        household_name="Synthetic household",
    )

    def override_db() -> Iterator[Session]:
        yield database_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, base_url="https://testserver") as client:
        yield client, database_session, settings
    app.dependency_overrides.clear()
    database_session.close()
    engine.dispose()


def test_secure_mode_is_deny_by_default_and_health_remains_public(
    secure_client: tuple[TestClient, Session, Settings],
) -> None:
    client, _, _ = secure_client

    assert client.get("/health").status_code == 200
    response = client.get("/transactions")
    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


def test_login_uses_opaque_cookie_rotates_csrf_and_logout_revokes_session(
    secure_client: tuple[TestClient, Session, Settings],
) -> None:
    client, session, _ = secure_client

    login = client.post(
        "/auth/login",
        json={"login": "owner", "password": OWNER_PASSWORD},
        headers=ORIGIN_HEADERS,
    )
    assert login.status_code == 200
    csrf_token = login.json()["csrf_token"]
    cookie_header = login.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=lax" in cookie_header

    stored_session = session.scalar(
        select(AuthSession).execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    )
    assert stored_session is not None
    raw_cookie = client.cookies.get("__Host-hic_session")
    assert raw_cookie is not None
    assert stored_session.token_digest != raw_cookie
    assert len(stored_session.token_digest) == 64

    current = client.get("/auth/session")
    assert current.status_code == 200
    rotated_csrf = current.json()["csrf_token"]
    assert rotated_csrf and rotated_csrf != csrf_token
    assert client.get("/transactions").status_code == 200

    denied_logout = client.post("/auth/logout", headers=ORIGIN_HEADERS)
    assert denied_logout.status_code == 403
    logout = client.post(
        "/auth/logout",
        headers={**ORIGIN_HEADERS, "X-CSRF-Token": rotated_csrf},
    )
    assert logout.status_code == 204
    assert client.get("/transactions").status_code == 401


def test_login_failures_are_generic_rate_limited_and_redacted(
    secure_client: tuple[TestClient, Session, Settings],
) -> None:
    client, session, _ = secure_client
    key = "testclient:missing"
    login_rate_limiter.clear(key)

    for _ in range(2):
        response = client.post(
            "/auth/login",
            json={"login": "missing", "password": "not-the-password"},
            headers=ORIGIN_HEADERS,
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid credentials"}
    limited = client.post(
        "/auth/login",
        json={"login": "missing", "password": "not-the-password"},
        headers=ORIGIN_HEADERS,
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"

    audit_events = session.scalars(
        select(SecurityAuditEvent).execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    ).all()
    serialized = " ".join(
        str(value)
        for event in audit_events
        for value in (event.event_type, event.outcome, event.detail_code)
    )
    assert "not-the-password" not in serialized
    login_rate_limiter.clear(key)


def test_expired_session_is_rejected(
    secure_client: tuple[TestClient, Session, Settings],
) -> None:
    client, session, _ = secure_client
    response = client.post(
        "/auth/login",
        json={"login": "owner", "password": OWNER_PASSWORD},
        headers=ORIGIN_HEADERS,
    )
    assert response.status_code == 200
    auth_session = session.scalar(
        select(AuthSession).execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
    )
    assert auth_session is not None
    auth_session.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()

    assert client.get("/auth/session").status_code == 401


def test_local_mode_preserves_single_household_development_workflow() -> None:
    settings = Settings(app_env="test", auth_mode="local")
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            response = client.get("/auth/session")
            assert response.status_code == 200
            assert response.json()["mode"] == "local"
    finally:
        app.dependency_overrides.clear()
