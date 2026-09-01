from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: Annotated[str, Field(min_length=3, max_length=100)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Annotated[str, Field(min_length=1, max_length=1024)]
    new_password: Annotated[str, Field(min_length=12, max_length=1024)]


class AuthSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "secure"]
    authenticated: Literal[True] = True
    login: str | None
    role: str
    csrf_token: str | None
