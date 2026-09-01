from email.utils import parseaddr
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Home Intelligence Copilot API"
    app_env: Literal["development", "test", "production"] = "development"
    api_docs_enabled: bool = False
    api_root_path: str = ""
    database_url: str = (
        "postgresql+psycopg://home_intelligence:local-development-only"
        "@localhost:5432/home_intelligence"
    )
    max_upload_size_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    document_storage_root: Path = Path("../data/documents")
    max_document_size_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_document_pages: int = Field(default=500, gt=0)
    max_document_text_chars: int = Field(default=2_000_000, gt=0)
    document_ocr_enabled: bool = True
    document_ocr_language: str = Field(
        default="eng",
        pattern=r"^[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*$",
    )
    document_ocr_timeout_seconds: int = Field(default=120, gt=0, le=900)
    auth_mode: Literal["local", "secure"] = "local"
    auth_allowed_origin: str = "http://localhost:5173"
    auth_allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost:8000", "127.0.0.1:8000"]
    )
    auth_session_idle_seconds: int = Field(default=30 * 60, gt=0)
    auth_session_absolute_seconds: int = Field(default=12 * 60 * 60, gt=0)
    auth_session_touch_interval_seconds: int = Field(default=60, ge=0)
    auth_login_attempt_limit: int = Field(default=5, gt=0)
    auth_login_window_seconds: int = Field(default=5 * 60, gt=0)

    document_extraction_stale_seconds: int = Field(default=300, ge=0)
    document_chunk_max_chars: int = Field(default=1000, gt=0)
    gmail_ingestion_enabled: bool = False
    gmail_client_id: SecretStr | None = None
    gmail_client_secret: SecretStr | None = None
    gmail_refresh_token: SecretStr | None = None
    gmail_ingestion_household_id: UUID | None = None
    gmail_allowed_senders: list[str] = Field(default_factory=list)
    gmail_require_authenticated_sender: bool = True
    gmail_search_query: str = Field(
        default="has:attachment filename:pdf -label:HIC/Imported -label:HIC/Failed",
        min_length=1,
        max_length=500,
    )
    gmail_processed_label: str = Field(default="HIC/Imported", min_length=1, max_length=225)
    gmail_failed_label: str = Field(default="HIC/Failed", min_length=1, max_length=225)
    gmail_poll_interval_seconds: int = Field(default=300, ge=30, le=86_400)
    gmail_max_messages_per_poll: int = Field(default=25, ge=1, le=100)
    gmail_ingestion_stale_seconds: int = Field(default=900, ge=60, le=86_400)
    gmail_max_attempts: int = Field(default=5, ge=1, le=20)
    household_timezone: str = "America/Los_Angeles"
    financial_features_enabled: bool = True
    ai_enabled: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    openai_max_output_tokens: int = Field(default=600, ge=100, le=4000)

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_authentication_settings(self) -> "Settings":
        if self.auth_session_absolute_seconds <= self.auth_session_idle_seconds:
            raise ValueError("absolute session timeout must exceed idle timeout")
        if not self.auth_allowed_hosts:
            raise ValueError("at least one allowed host is required")
        if (
            self.auth_mode == "secure"
            and self.app_env == "production"
            and not self.auth_allowed_origin.startswith("https://")
        ):
            raise ValueError("secure production mode requires an HTTPS allowed origin")
        if self.ai_enabled and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when AI_ENABLED is true")
        self.gmail_allowed_senders = sorted(
            {sender.strip().casefold() for sender in self.gmail_allowed_senders if sender.strip()}
        )
        invalid_senders = [
            sender
            for sender in self.gmail_allowed_senders
            if parseaddr(sender)[1].casefold() != sender or "@" not in sender
        ]
        if invalid_senders:
            raise ValueError("GMAIL_ALLOWED_SENDERS must contain complete email addresses")
        if self.gmail_ingestion_enabled:
            required = {
                "GMAIL_CLIENT_ID": self.gmail_client_id,
                "GMAIL_CLIENT_SECRET": self.gmail_client_secret,
                "GMAIL_REFRESH_TOKEN": self.gmail_refresh_token,
                "GMAIL_INGESTION_HOUSEHOLD_ID": self.gmail_ingestion_household_id,
            }
            missing = [
                name
                for name, value in required.items()
                if value is None
                or (isinstance(value, SecretStr) and not value.get_secret_value().strip())
            ]
            if missing:
                raise ValueError(f"Gmail ingestion requires {', '.join(missing)}")
            if not self.gmail_allowed_senders:
                raise ValueError("Gmail ingestion requires at least one allowed sender")
        try:
            ZoneInfo(self.household_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("HOUSEHOLD_TIMEZONE must be a valid IANA timezone") from exc
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
