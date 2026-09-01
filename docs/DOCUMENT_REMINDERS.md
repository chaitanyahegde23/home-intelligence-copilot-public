# Document expiration reminders

HIC-048 adds opt-in, in-app attention reminders on top of HIC-047 expiration facts. It does not run a background scheduler or send data to an external delivery service.

## Lifecycle

Each document can have at most one reminder configuration. A user explicitly enables it and chooses a lead window. `GET /documents/expiration-reminders` calculates the household-local date from `HOUSEHOLD_TIMEZONE`; callers may pass `as_of` for deterministic testing.

- **Acknowledge** records the current expiration date. That exact date stays suppressed, but a corrected or renewed expiration date appears again automatically.
- **Snooze** suppresses the current reminder through an explicit household calendar date.
- Disabling retains the configuration but removes it from attention results.
- Document deletion cascades the reminder configuration.

The only supported channel is `in_app`. Email, Slack, mobile push, background polling, retention actions, and automatic renewal are intentionally excluded.

## API

- `PUT /documents/{document_id}/expiration-reminder`
- `GET /documents/expiration-reminders`
- `POST /documents/{document_id}/expiration-reminder/acknowledge`
- `POST /documents/{document_id}/expiration-reminder/snooze`

The document library exposes reminder controls under **Edit details** and renders active items in a **Document reminders** attention panel with links to the source record.
