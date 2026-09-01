# Authentication and household-isolation architecture

## Decision status

Accepted and implemented by HIC-025. Local mode remains an explicit trusted-development workflow;
secure mode implements the owner/session/household boundary. Public production operation still
requires same-origin TLS, infrastructure hardening, protected backup/restore, and deployment review.

## Selected approach

The first secure release will use:

- one application-managed household owner account created by an explicit interactive operator
  command, with no public registration or invitation endpoint;
- normalized login name plus an Argon2id password hash using parameters stored with the hash; the
  current OWASP floor of 19 MiB memory, two iterations, and parallelism one; this portable floor is
  intentionally fixed for heterogeneous self-hosted development hardware and may be raised after deployment benchmarking;
- opaque 256-bit random session tokens in a `__Host-hic_session` cookie with `Secure`, `HttpOnly`,
  `SameSite=Lax`, `Path=/`, and no `Domain` attribute;
- only a SHA-256 digest of each session token in PostgreSQL;
- server-side session revocation, idle expiry, absolute expiry, and rotation at authentication or
  privilege changes;
- a synchronizer CSRF token plus Origin/Host validation for every state-changing request;
- same-origin frontend/API deployment behind TLS for secure mode; and
- a server-created request principal containing user ID, household ID, and role, passed to every
  protected service and approved tool.

Initial policy values should be explicit configuration with conservative defaults: a 30-minute idle
timeout and 12-hour absolute timeout, with longer-lived “remember me” sessions excluded. Exact
Argon2id uses the stated portable floor; rate limiting defaults to five attempts per five minutes.
Operators may tighten the rate/window settings after testing their deployment.

## Why this approach

It keeps household credentials and sessions inside the self-hosted privacy boundary, works without
an email service or third-party identity processor, supports immediate server-side revocation, and
avoids bearer tokens in browser-readable storage. It is appropriate for the first owner-operated
single-household deployment while leaving room for a later passkey or OIDC adapter.

## Rejected alternatives

| Alternative | Decision and reason |
| --- | --- |
| No authentication because the app is “personal” | Rejected for remote use; network reachability is not identity or household authorization. Local mode remains explicitly unsupported on untrusted networks. |
| Shared API key or Basic Auth | Rejected as the browser session model; weak logout/revocation/CSRF/user attribution and encourages long-lived copied secrets. |
| JWT access tokens in local/session storage | Rejected; increases XSS exposure, complicates revocation and rotation, and adds no value for the same-origin monolith. |
| Stateless JWT cookie | Rejected initially; revocation and privilege changes still require server state, so an opaque session is simpler and safer. |
| Client-supplied `household_id` or trusted UUID secrecy | Rejected; identity and scope must be derived from the authenticated server session. |
| Automatic trust for loopback/private IP or a development bypass header | Rejected in secure mode; these are easy to misconfigure or spoof through proxies. Tests may override dependencies explicitly without shipping a runtime bypass. |
| Mandatory external OIDC provider | Deferred; strong for organizations but adds availability, redirect, discovery, secret, and privacy dependencies for a personal self-hosted app. A later adapter must map verified provider identities to local users and sessions. |
| Passkey-only/WebAuthn | Deferred; phishing-resistant and desirable, but recovery, origin/TLS setup, device compatibility, and implementation scope exceed the first ownership foundation. |
| Email magic link/password reset | Deferred because no email processor exists. Initial recovery is a local interactive operator workflow that revokes sessions and resets the owner credential without logging the new secret. |

## Identity and ownership model

HIC-025 should introduce these roots:

| Entity | Minimum contract |
| --- | --- |
| `Household` | UUID, nonblank display name, active state, timezone-aware timestamps |
| `User` | UUID, household ID, normalized unique login within household, Argon2id password hash, owner/member role, active state, password-changed timestamp, timestamps |
| `AuthSession` | UUID, user and household IDs, unique SHA-256 token digest, issued/last-seen/idle-expiry/absolute-expiry/revoked timestamps, bounded non-sensitive creation metadata |
| `SecurityAuditEvent` | UUID, household/user/session references when known, allowlisted event type/outcome, target type/ID when safe, timestamp, optional coarse source fingerprint; never credentials, token, raw IP, filename, transaction, document text, prompt, or response |

The first release creates exactly one bootstrap household and owner through an explicit local command.
The schema may support a `member` role, but public registration, invitations, membership management,
multiple active households per user, impersonation, and role-administration UI remain excluded.

## Sensitive-table ownership

Every sensitive row must have an authoritative non-null `household_id`, including:

- import batches and transactions;
- categories, categorization rules, assignments, and duplicate candidates;
- documents, deletion audits, extraction runs, text spans, and chunks; and
- future prompts, model runs, evaluations containing household-derived data, citations, exports, and
  audit events.

Parent/child tables must prevent mismatched household IDs with composite foreign-key or equivalent
database constraints. Global uniqueness that can reveal or conflict across households must become
household-scoped, including document checksum/size and category names. Indexes for protected queries
must lead with `household_id` where appropriate.

Do not accept `household_id` as a public filter or write field. Services use the principal's value.
Foreign and absent resources return the same not-found response unless a documented owner-only audit
surface requires otherwise.

## Request and session flow

1. The reverse proxy serves frontend and API under one HTTPS origin and forwards an allowlisted Host.
2. The login endpoint validates bounded normalized credentials with a generic response and rate
   limits before/after password verification.
3. On success, the server rotates any presented session, creates a random token, stores its digest,
   and sets the secure session cookie. The raw token is never persisted or logged.
4. A deny-by-default dependency hashes the cookie, loads a non-revoked/non-expired session and active
   user/household, and creates `RequestPrincipal`.
5. Protected routes pass the principal to services; household scope is applied before lookup,
   mutation, aggregation, lexical matching, or tool execution.
6. State-changing requests also require the synchronizer CSRF token and valid Origin/Host.
7. Logout revokes the server session and expires the cookie. Password change/recovery revokes all
   sessions for that user and records a redacted audit event.

Session last-seen writes should be throttled so every request does not create database write load.
Inactive, expired, and revoked sessions fail identically.

## Route and tool integration

- Apply a protected dependency at the API-router boundary. Explicitly carve out only minimal health,
  login, and bootstrap-status routes.
- Keep auth parsing in dependencies/middleware, authorization in household-scoped services, and
  business rules in existing services; route handlers remain thin.
- Replace unconstrained `session.get(Model, id)` and root queries with household-scoped lookup
  helpers or repositories. Code review must treat an unscoped sensitive query as a defect.
- Analytics functions receive household scope and include it in every source query before
  aggregation.
- The immutable tool executor receives a `RequestPrincipal` separately from model-controlled tool
  arguments. Household identity never appears in the JSON tool schema.
- Document blob reads follow an authorized metadata lookup; storage keys alone never authorize.
- Extraction, chunk creation, and retrieval scope both their root document and derivatives. Future
  vector/lexical candidate selection includes household scope before ranking.
- Secure mode authenticates or disables `/docs` and `/openapi.json`; application exception messages
  do not reveal foreign resources or credentials.

## CSRF, browser, and proxy controls

- Use only the session cookie for authentication; do not expose it to JavaScript.
- Send a separate CSRF token in a custom header for unsafe methods and verify it against server-side
  session state with constant-time comparison. Deliver it through an authenticated JSON response,
  never a cookie, URL, HTML log, or error.
- Require a same-origin Origin for browser unsafe methods and validate the effective Host against
  configuration. A missing Origin needs an explicit non-browser policy; it is not silently trusted.
- Reject `Sec-Fetch-Site: cross-site` on unsafe methods as defense in depth; Origin/Host validation
  remains the mandatory fallback when Fetch Metadata is missing.
- Do not enable wildcard or reflected credentialed CORS. A later separate-origin client requires a
  new ADR and exact origin allowlist.
- Reverse proxy must enforce TLS, request-body limits, security headers, and trusted forwarded-header
  sources. Direct API exposure remains private.
- Recommended headers for secure mode include HSTS at the TLS edge, a restrictive CSP,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and clickjacking protection via
  CSP `frame-ancestors`.

## Existing-data migration

HIC-025 implements this deliberate maintenance-window migration sequence:

1. Back up PostgreSQL and the private blob volume and verify the current Alembic head.
2. Create identity/session/audit tables and one bootstrap household with a server-generated UUID.
3. Add nullable `household_id` columns temporarily to every sensitive table.
4. Backfill top-level rows to the bootstrap household, then children from their authoritative parent.
5. Assert zero nulls, zero parent/child household mismatches, and unchanged row counts/checksums.
6. Replace global uniqueness with household-scoped constraints and add household-leading indexes.
7. Add parent/child household consistency constraints and make all ownership columns non-null.
8. Create the owner interactively; keep network exposure local until the owner and secure-mode
   configuration pass startup checks.
9. Upgrade, verify, downgrade only in a disposable copy, re-upgrade, and run Alembic drift checks.

The migration must not infer households from account names, filenames, categories, directories, or
client input. Existing rows all belong to the single bootstrap household. A failed backfill aborts;
there is no nullable steady state or “unknown household.”

## Recovery and lifecycle

- Initial credential recovery is an interactive local operator command requiring database access;
  it sets a new password hash, revokes every owner session, and writes a redacted audit event.
- Never accept a recovery password in a command argument, environment variable, URL, log, or issue.
- Session cleanup deletes expired/revoked rows after a documented bounded retention period while
  retaining only non-sensitive audit events required for operations.
- Household export and delete-account/delete-household workflows are separate reviewed tasks. They
  require re-authentication, complete derivative/blob handling, and recovery-set policy.
- Backup/restore must cover the database and blob volume as one logical recovery point and be tested
  with synthetic data.

## HIC-025 implemented acceptance gates

- Unauthenticated requests fail for every sensitive API, tool, document, and retrieval surface.
- Login failures are generic; passwords and raw session/CSRF tokens never persist in logs or the
  database.
- Cookie flags, idle/absolute expiry, rotation, logout, password-change revocation, and recovery are
  tested.
- CSRF and Origin/Host checks reject forged state-changing requests; allowed same-origin requests
  pass.
- Authorization-matrix and IDOR tests cover list, detail, filters, writes, analytics, tools,
  documents, extraction, chunks, search, and deletion.
- Database tests prove non-null ownership, parent/child consistency, and household-scoped uniqueness.
- Migration tests prove deterministic bootstrap backfill, unchanged data counts, reversibility on a
  disposable database, and no Alembic drift.
- Audit tests prove allowlisted events and payload redaction.
- Rate-limit, body-limit, and secure-startup misconfiguration tests fail closed.
- Docker and browser tests exercise login, protected navigation, expiry/logout, CSRF failure, and a
  cross-household denial using synthetic data only.

## Explicit HIC-025 exclusions

Passkeys, MFA, OIDC/social login, email recovery, public registration, invitations, multi-household
membership, granular per-record sharing, mobile tokens, API keys, service accounts, enterprise SSO,
document download, household export/deletion, and public deployment automation require later scoped
decisions. None may be introduced silently while implementing the foundation.

## Security guidance baseline

HIC-025 review maps its controls to the relevant OWASP ASVS authentication, session, access
control, validation, and logging requirements. The selected primitives align with:

- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
