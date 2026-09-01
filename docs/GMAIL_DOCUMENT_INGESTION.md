# Gmail document ingestion

HIC can poll one dedicated Gmail mailbox for PDF attachments and feed them through the same private
document validation, storage, OCR, metadata/fact extraction, and search-indexing pipeline used by
manual uploads. Gmail ingestion is disabled by default and runs in a separate Docker worker.

## Security and privacy contract

- Use Google OAuth 2.0 with the narrow `https://www.googleapis.com/auth/gmail.modify` scope. Never
  configure or store the Gmail password.
- Only exact addresses in `GMAIL_ALLOWED_SENDERS` may provide documents. Sender display names are
  ignored. By default, Gmail must also report DMARC authentication success and must not classify the
  message as spam; this makes the visible `From` allowlist materially harder to spoof.
- Only PDF attachments are considered. Existing byte, page, structural-content, duplicate, OCR,
  and text limits remain authoritative.
- The application stores sender, subject, received time, original filename, status, and document
  link for auditability. It does not store the email body. Provider message/attachment identifiers
  are stored for idempotency but are not returned by the API.
- OAuth credentials and refresh tokens belong only in the ignored root `.env`. They must not appear
  in source control, screenshots, issue trackers, or logs.
- Successful messages receive `HIC/Imported`. Permanently rejected or retry-exhausted messages
  receive `HIC/Failed`. Transient failures remain unlabeled so the bounded retry policy can run.

## One-time Google setup

1. Create or select a Google Cloud project owned by the household administrator.
2. Enable **Gmail API**.
3. Configure the OAuth consent screen. For a personal Gmail account, add the dedicated document
   mailbox as a test user while the app remains in testing.
4. Create an OAuth client of type **Desktop app**. Copy its client ID and client secret into `.env`.
5. In Google's OAuth 2.0 Playground, open settings, enable **Use your own OAuth credentials**, and
   enter that client ID and secret.
6. Authorize `https://www.googleapis.com/auth/gmail.modify` while signed into the dedicated mailbox,
   exchange the authorization code, and copy the refresh token into `.env`.
7. Treat the refresh token like a password. Revoke it from the Google account immediately if it is
   exposed.

The Google OAuth consent/test-user state controls refresh-token lifetime. If Google invalidates a
token, the worker records only a redacted OAuth error code and stops importing until a replacement
token is configured.

## HIC configuration

Copy the placeholder keys from `.env.example` and set:

```text
GMAIL_INGESTION_ENABLED=true
GMAIL_CLIENT_ID=<Google desktop OAuth client ID>
GMAIL_CLIENT_SECRET=<Google desktop OAuth client secret>
GMAIL_REFRESH_TOKEN=<refresh token for the dedicated mailbox>
GMAIL_INGESTION_HOUSEHOLD_ID=<the HIC household UUID>
GMAIL_ALLOWED_SENDERS=["first.allowed@example.com","second.allowed@example.com"]
GMAIL_REQUIRE_AUTHENTICATED_SENDER=true
```

The Compose files read the sender list from `GMAIL_ALLOWED_SENDERS_JSON`, so set the same JSON value
there when Compose is used:

```text
GMAIL_ALLOWED_SENDERS_JSON=["first.allowed@example.com","second.allowed@example.com"]
```

List the production household UUID without exposing credentials:

```powershell
docker compose -f compose.production.yaml exec db sh -lc `
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT id, display_name FROM households;"'
```

Keep the default query and labels unless there is a reviewed operational reason to change them.
The default poll interval is five minutes, each poll considers at most 25 messages, and transient
attachments receive at most five attempts.

## Run locally

Apply migrations, then start the API and Gmail worker profile:

```powershell
docker compose up -d --build db api
docker compose exec api python -m alembic upgrade head
docker compose --profile gmail up -d --build gmail-worker
docker compose --profile gmail logs --tail 100 gmail-worker
```

Send a synthetic PDF from an allowlisted address to the dedicated mailbox. Within one polling
interval it should appear in Documents with an **Imported from Gmail** provenance chip and become
searchable. Inspect the protected audit endpoint from a signed-in browser at
`/api/gmail-ingestions`; it never returns OAuth credentials, message bodies, or provider IDs.

## Run in production

After updating the ignored production `.env`:

```powershell
docker compose -f compose.production.yaml up -d --build api web
docker compose -f compose.production.yaml --profile gmail up -d --build gmail-worker
docker compose -f compose.production.yaml --profile gmail ps
docker compose -f compose.production.yaml --profile gmail logs --tail 100 gmail-worker
```

The worker shares the API's private document volume and database network and has a separate
outbound network for Google OAuth/Gmail HTTPS calls. It publishes no port.
Stopping it pauses email ingestion without affecting manual uploads or existing documents.

## Known limitations

- One configured Gmail mailbox and one destination household per deployment.
- PDF attachments only; email bodies, inline images, archives, and office files are ignored.
- Polling rather than Gmail push/Pub/Sub; delivery is normally delayed by up to one poll interval.
- Exact sender allowlisting and DMARC success; aliases/forwarders must be explicitly listed and may
  need reviewed handling if forwarding breaks authentication.
- No mailbox connection UI or manual “poll now” action. Configuration is an operator task.
- The first page of a bounded Gmail query is processed per poll; labels remove terminal messages
  from subsequent queries.
