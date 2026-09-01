# Example production deployment

This runbook deploys Home Intelligence Copilot on the Windows laptop at
`https://hic.example.com`. Cloudflare Access authenticates an allowlisted browser before an
outbound-only Cloudflare Tunnel forwards the request to the local web container. Caddy serves the
production frontend and proxies same-origin `/api` requests to FastAPI. PostgreSQL and FastAPI have
no published host ports.

## Security boundary

- Cloudflare Access must exist for `hic.example.com` before the tunnel route is published.
- The Access policy must be deny-by-default and allow only exact household email addresses.
- Do not create an `A`/`AAAA` record for the residential IP or forward router ports.
- `AUTH_MODE=secure`, the HTTPS origin, and the allowed host are fixed in
  `compose.production.yaml`; production startup fails closed if those settings become invalid.
- The API runs one worker because login throttling is process-local.
- Production disables `/docs`, `/redoc`, and `/openapi.json` by default. Set
  `API_DOCS_ENABLED=true` only when Swagger access is needed; Cloudflare Access must continue to
  protect the hostname.
- The Cloudflare route must target `http://web:8080`, never ports `5173`, `8000`, or `5432`.
- The loopback-only `127.0.0.1:8080` mapping exists for local health checks and recovery.

## Local secret preparation

The ignored root `.env` supplies secrets to both Compose files. Before production startup, confirm:

```text
POSTGRES_PASSWORD=<unique URL-safe random password of at least 32 characters>
AI_ENABLED=false
CLOUDFLARE_TUNNEL_TOKEN=<token copied from the example HIC tunnel>
```

Use only letters and digits in `POSTGRES_PASSWORD` because Compose embeds it into the SQLAlchemy
database URL. Enable AI only when `OPENAI_API_KEY` contains a valid project key. Never commit, paste,
or screenshot `.env`, passwords, API keys, or tunnel tokens.

## Validate the configuration

From the repository root:

```powershell
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml build api web
```

## Start the private production core

This command reuses the existing `postgres_data` volume and `data/documents` directory. The API
applies committed Alembic migrations before starting.

```powershell
docker compose -f compose.production.yaml up -d --build db api web
docker compose -f compose.production.yaml ps
Invoke-RestMethod http://127.0.0.1:8080/healthz
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

The first endpoint returns `ok`; the second returns `{"status":"ok"}`. A request to
`http://127.0.0.1:8080/api/openapi.json` must return 404.

## Bootstrap or recover the owner

Create the first owner interactively. The command reads the password twice from the terminal using
hidden input and never accepts it through arguments or environment variables.

```powershell
docker compose -f compose.production.yaml exec api `
  python -m app.cli create-owner --login owner --household-name "Example household"
```

If the owner already exists, use the recovery command instead:

```powershell
docker compose -f compose.production.yaml exec api `
  python -m app.cli reset-owner-password --login owner
```

## Create the remotely managed tunnel

1. In Cloudflare Zero Trust, open **Networking → Tunnels**.
2. Create a Cloudflared tunnel named `example-hic`.
3. Choose Docker as the connector environment.
4. Copy only the token from the generated command into the local ignored `.env` as
   `CLOUDFLARE_TUNNEL_TOKEN`.
5. Add a published application route:
   - Hostname: `hic.example.com`
   - Service type: HTTP
   - Service URL: `web:8080`
6. Enable **Protect with Access** and select the example `HIC` Access application.
7. Do not create a second Access application or a public-IP DNS record.

Start the connector only after the route is protected:

```powershell
docker compose -f compose.production.yaml --profile tunnel up -d tunnel
docker compose -f compose.production.yaml --profile tunnel ps
```

## Optional Gmail document intake

Complete [`GMAIL_DOCUMENT_INGESTION.md`](GMAIL_DOCUMENT_INGESTION.md), including the dedicated
mailbox OAuth grant, exact sender allowlist, and destination household UUID. Then start the private
worker profile:

```powershell
docker compose -f compose.production.yaml --profile gmail up -d --build gmail-worker
docker compose -f compose.production.yaml --profile gmail ps
docker compose -f compose.production.yaml --profile gmail logs --tail 100 gmail-worker
```

The worker publishes no host port. It shares the API's private document volume, joins the internal
database network, and uses a separate egress network for Google HTTPS calls. Do not add it to the
Cloudflare route.

Cloudflare recommends remotely managed tunnels for Docker and publishes the official connector as
`cloudflare/cloudflared:latest`. Update it deliberately with:

```powershell
docker compose -f compose.production.yaml --profile tunnel pull tunnel
docker compose -f compose.production.yaml --profile tunnel up -d tunnel
```

## Acceptance checks

1. Turn off Wi-Fi on the phone and open `https://hic.example.com` over cellular data.
2. An unapproved email must be denied by Cloudflare Access.
3. The approved owner must pass Cloudflare Access and then reach the HIC login screen.
4. Sign in with the local HIC owner credential and verify Dashboard, Documents, and Copilot.
5. Confirm `https://hic.example.com/api/openapi.json` returns 404.
6. Confirm the browser console has no errors and responsive layout remains usable.
7. Upload only a synthetic fixture for the first public-flow test.

## Operations

- Keep the laptop connected to AC power and wired Ethernet where possible.
- Configure Docker Desktop to start at Windows sign-in and ensure the Windows account signs in after
  planned reboots. Verify every enabled core/profile container after each Windows or Docker update.
- Monitor container state with:

  ```powershell
  docker compose -f compose.production.yaml --profile tunnel ps
  docker compose -f compose.production.yaml --profile tunnel logs --tail 100
  ```

- Never copy the live PostgreSQL Docker volume as a backup. Use `pg_dump` and back up
  `data/documents` as the same logical recovery point.
- Keep encrypted, versioned backups on a BitLocker-protected external disk and test restoration with
  synthetic data. An always-attached disk is not an off-site or ransomware-resistant copy.

## Stop or roll back

Stop the production application without deleting data:

```powershell
docker compose -f compose.production.yaml --profile tunnel down
```

Never add `--volumes`; that would delete the PostgreSQL volume. To return temporarily to the trusted
local development stack, keep the Cloudflare tunnel stopped and run the documented development
Compose and Vite commands.
