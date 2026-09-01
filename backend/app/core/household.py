from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

BOOTSTRAP_HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class RequestPrincipal:
    household_id: UUID
    user_id: UUID | None
    role: str
    auth_session_id: UUID | None
    is_local_mode: bool = False


LOCAL_PRINCIPAL = RequestPrincipal(
    household_id=BOOTSTRAP_HOUSEHOLD_ID,
    user_id=None,
    role="owner",
    auth_session_id=None,
    is_local_mode=True,
)

_current_principal: ContextVar[RequestPrincipal] = ContextVar(
    "current_request_principal",
    default=LOCAL_PRINCIPAL,
)


def get_current_principal() -> RequestPrincipal:
    return _current_principal.get()


def get_current_household_id() -> UUID:
    return get_current_principal().household_id


@contextmanager
def principal_scope(principal: RequestPrincipal) -> Iterator[None]:
    token = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)
