# Security

## Secrets

- Secrets live only in the deployment's variables (Railway) and, locally, in
  `.env` / `.env.local` files that Git ignores (`.gitignore`: `.env`, `.env.*`
  except `.env.example`). `.env.example` holds names and safe defaults only.
- Server secrets never go into `NEXT_PUBLIC_*`, the browser, a response body, a
  log line or a test snapshot. The only server variable on the web app is
  `REVALIDATE_SECRET`, which can do nothing but clear a cached page.
- Logging (`platform_core/logging.py`) redacts any value whose key contains
  `secret`, `token`, `password`, `credential`, `authorization` and similar before
  rendering; `test_logging_redaction.py` holds it to that.
- Tests can never spend AI credit or reach a deployed database:
  `LOCAH_TEST_NO_EXTERNAL_AI` refuses paid calls, and the test database guard
  refuses a remote `DATABASE_URL` unless a dedicated `TEST_DATABASE_URL` is set.

## Tenant isolation

- The API resolves every Business-scoped request through one gate chain
  (membership → Business → Entitlement → module state → permission), then
  narrows by Location scope and assignment scope. The client never decides what a
  person may do; hidden navigation is not authorization.
- Queries carry explicit Business predicates. RLS on every tenant table (API role
  `platform_api`) is defence in depth, not the primary check.
- Isolation is tested: cross-business access tests, an actor/permission matrix, and
  suites that run as the RLS role.
- The worker uses the owner role for cross-tenant jobs; it never serves a request.

## Payment and provider credentials

- Each business's provider credentials and tokens (payments, WhatsApp) are
  encrypted at rest with `PAYMENT_CREDENTIAL_KEY` (Fernet, `platform_core/crypto.py`)
  and are never returned once stored.
- Merchant collection and platform billing are separate code paths.
- Payment state moves only on a provider webhook whose signature verifies against
  `PAYMENT_WEBHOOK_SECRET`; each event is stored once (`payments_webhook_receipts`,
  keyed by provider event id), so a repeated delivery changes nothing. Browser
  callbacks are never payment truth. Refunds can never exceed what was paid
  (row lock in the kernel).
- WhatsApp webhooks verify Meta's signature with `META_APP_SECRET`; without it and
  `WHATSAPP_VERIFY_TOKEN` the routes answer 404.

## Website and AI boundaries

- Tenant websites are structured content; AI writes words and picks allowed
  layouts, never markup, scripts or platform mechanics (cart, checkout, booking,
  payment, permissions).
- Draft previews use short-lived signed preview tokens; a draft is never public.
- AI employees act only through allowlisted tools within tiers and limits; owner
  matters (discounts, refunds, rule changes) always go to a person.

## Repository and CI rules

- `.github/workflows/` contains only `ci.yml`. Any workflow that prints, encodes,
  uploads or forwards `secrets`, environment variables or credentials is malicious —
  delete the branch, rotate every secret the repository or its environments hold,
  and review the account's tokens, keys and sessions.
- Protect `main`; never push or deploy from a machine that may be compromised, and
  rotate credentials from a clean device.

## Known limits

- Payment webhooks are verified, deduplicated and applied within the request;
  failures are recorded on the receipt but are not yet re-queued to the worker or
  surfaced as dead letters.
- Refunds lock the payment, are capped by what was paid, and take an
  `idempotency_key` (the Workspace sends one per refund form): a retried request
  returns the refund already made. API callers that omit the key get no retry
  protection beyond the cap and the optional `version` check.
