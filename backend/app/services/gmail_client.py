from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr
from time import monotonic
from typing import Any, Protocol
from urllib.parse import quote

import httpx


class GmailApiError(RuntimeError):
    """A redacted Gmail API failure safe for application logs and status records."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GmailAttachment:
    attachment_key: str
    api_attachment_id: str | None
    filename: str
    media_type: str
    declared_size: int
    inline_data: str | None


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    sender: str
    subject: str | None
    received_at: datetime
    attachments: tuple[GmailAttachment, ...]
    authenticated_sender: bool
    is_spam: bool


class GmailClientProtocol(Protocol):
    def list_message_ids(self, *, query: str, limit: int) -> tuple[str, ...]: ...

    def get_message(self, message_id: str) -> GmailMessage: ...

    def download_attachment(self, message_id: str, attachment: GmailAttachment) -> bytes: ...

    def label_message(self, message_id: str, *, add: str, remove: str | None = None) -> None: ...


class GmailClient:
    _api_root = "https://gmail.googleapis.com/gmail/v1/users/me"
    _token_url = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        timeout_seconds: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._http = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_http_client = http_client is None
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._label_ids: dict[str, str] = {}

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def list_message_ids(self, *, query: str, limit: int) -> tuple[str, ...]:
        payload = self._request_json(
            "GET",
            "/messages",
            params={"q": query, "maxResults": str(limit)},
        )
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise GmailApiError("invalid_message_list")
        ids = [item.get("id") for item in messages if isinstance(item, dict)]
        return tuple(value for value in ids if isinstance(value, str) and value)

    def get_message(self, message_id: str) -> GmailMessage:
        payload = self._request_json(
            "GET",
            f"/messages/{quote(message_id, safe='')}",
            params={"format": "full"},
        )
        root_part = payload.get("payload")
        if not isinstance(root_part, dict):
            raise GmailApiError("invalid_message_payload")
        headers = _headers(root_part)
        sender = parseaddr(headers.get("from", ""))[1].strip().casefold()
        if not sender:
            raise GmailApiError("missing_sender")
        internal_date = payload.get("internalDate")
        try:
            timestamp_ms = _safe_int(internal_date)
            if timestamp_ms <= 0:
                raise ValueError
            received_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
        except (ValueError, OSError) as exc:
            raise GmailApiError("invalid_received_date") from exc
        return GmailMessage(
            message_id=message_id,
            sender=sender,
            subject=_normalized_optional(headers.get("subject"), 500),
            received_at=received_at,
            attachments=tuple(_pdf_attachments(root_part)),
            authenticated_sender="dmarc=pass"
            in headers.get("authentication-results", "").casefold(),
            is_spam="SPAM" in _string_values(payload.get("labelIds")),
        )

    def download_attachment(self, message_id: str, attachment: GmailAttachment) -> bytes:
        if attachment.inline_data is not None:
            return _decode_base64url(attachment.inline_data)
        if attachment.api_attachment_id is None:
            raise GmailApiError("missing_attachment_data")
        payload = self._request_json(
            "GET",
            f"/messages/{quote(message_id, safe='')}/attachments/"
            f"{quote(attachment.api_attachment_id, safe='')}",
        )
        data = payload.get("data")
        if not isinstance(data, str):
            raise GmailApiError("missing_attachment_data")
        return _decode_base64url(data)

    def label_message(self, message_id: str, *, add: str, remove: str | None = None) -> None:
        add_id = self._ensure_label(add)
        remove_ids = [self._ensure_label(remove)] if remove else []
        self._request_json(
            "POST",
            f"/messages/{quote(message_id, safe='')}/modify",
            json={"addLabelIds": [add_id], "removeLabelIds": remove_ids},
        )

    def _ensure_label(self, label_name: str) -> str:
        if label_name in self._label_ids:
            return self._label_ids[label_name]
        labels = self._request_json("GET", "/labels").get("labels", [])
        if not isinstance(labels, list):
            raise GmailApiError("invalid_label_list")
        for label in labels:
            if isinstance(label, dict) and label.get("name") == label_name:
                label_id = label.get("id")
                if isinstance(label_id, str):
                    self._label_ids[label_name] = label_id
                    return label_id
        created = self._request_json(
            "POST",
            "/labels",
            json={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        label_id = created.get("id")
        if not isinstance(label_id, str) or not label_id:
            raise GmailApiError("invalid_created_label")
        self._label_ids[label_name] = label_id
        return label_id

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._get_access_token()
        try:
            response = self._http.request(
                method,
                f"{self._api_root}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise GmailApiError("gmail_unavailable") from exc
        if response.status_code == 401:
            self._access_token = None
        if response.is_error:
            raise GmailApiError(f"gmail_http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GmailApiError("invalid_gmail_response") from exc
        if not isinstance(payload, dict):
            raise GmailApiError("invalid_gmail_response")
        return payload

    def _get_access_token(self) -> str:
        if self._access_token is not None and monotonic() < self._access_token_expires_at:
            return self._access_token
        try:
            response = self._http.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise GmailApiError("oauth_unavailable") from exc
        if response.is_error:
            raise GmailApiError(f"oauth_http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GmailApiError("invalid_oauth_response") from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        expires_in = payload.get("expires_in", 3600) if isinstance(payload, dict) else 3600
        if not isinstance(token, str) or not token:
            raise GmailApiError("missing_access_token")
        try:
            ttl = max(60, int(expires_in))
        except (TypeError, ValueError):
            ttl = 3600
        self._access_token = token
        self._access_token_expires_at = monotonic() + ttl - 30
        return token


def _headers(part: dict[str, Any]) -> dict[str, str]:
    headers = part.get("headers", [])
    if not isinstance(headers, list):
        return {}
    return {
        str(item["name"]).casefold(): str(item["value"])
        for item in headers
        if isinstance(item, dict) and "name" in item and "value" in item
    }


def _pdf_attachments(part: dict[str, Any]) -> list[GmailAttachment]:
    found: list[GmailAttachment] = []
    filename = str(part.get("filename", "")).strip()
    media_type = str(part.get("mimeType", "")).casefold()
    body = part.get("body", {})
    if (
        filename
        and isinstance(body, dict)
        and (filename.casefold().endswith(".pdf") or media_type == "application/pdf")
    ):
        api_id = body.get("attachmentId")
        inline_data = body.get("data")
        part_id = str(part.get("partId", "root"))
        key = str(api_id) if api_id else f"inline:{part_id}"
        declared_size = _safe_int(body.get("size"))
        found.append(
            GmailAttachment(
                attachment_key=key,
                api_attachment_id=str(api_id) if api_id else None,
                filename=filename[:255],
                media_type=media_type,
                declared_size=declared_size,
                inline_data=str(inline_data) if inline_data else None,
            )
        )
    children = part.get("parts", [])
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                found.extend(_pdf_attachments(child))
    return found


def _decode_base64url(value: str) -> bytes:
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise GmailApiError("invalid_attachment_encoding") from exc


def _normalized_optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())[:limit]
    return normalized or None


def _safe_int(value: object) -> int:
    if not isinstance(value, str | bytes | bytearray | int):
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _string_values(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}
