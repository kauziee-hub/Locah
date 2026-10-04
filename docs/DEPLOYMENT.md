# Deployment

Production runs on **Railway** (project `locah-staging`, environment `production`).
**Supabase** is the database, auth and storage. Every Railway service builds the
GitHub `main` branch of `kausik-gh/locah` with its own Dockerfile; nothing is
uploaded from a laptop and nothing is patched on Railway outside Git.

## Services

| Railway service | Dockerfile | Start | Health |
|---|---|---|---|
| `locah-api` | `infra/docker/Dockerfile.api` | `uv run uvicorn platform_api.main:app --host 0.0.0.0 --port $PORT` | `/health/ready`, `/health/live` |
| `locah-worker` | `infra/docker/Dockerfile.worker` | `uv run python -m platform_worker.main` | logs `worker.polling`; API `/health/worker` alarms on outbox lag |
| `locah-web` | `infra/docker/Dockerfile.web` | `pnpm --filter @platform/web exec next start` | `/` |
| `locah-workspace` | `infra/docker/Dockerfile.workspace` | `pnpm --filter @platform/workspace exec next start` | `/` |

`apps/admin` builds in CI but is not a public Railway service yet. Each service
watches only its own paths (its app, `python/**` or `packages/**`, its Dockerfile,
lockfiles), so a push redeploys only what changed.

## Environment variables (names only)

**locah-api** — secrets: `DATABASE_URL`, `API_DATABASE_URL` (RLS role
`platform_api`), `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` (legacy HS256
only), `WEBSITE_PREVIEW_SECRET`, `PAYMENT_WEBHOOK_SECRET`, `PAYMENT_CREDENTIAL_KEY`,
`GEMINI_API_KEY`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`; when WhatsApp is
activated `META_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`. Config: `ENVIRONMENT=production`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `CORS_ALLOWED_ORIGINS`, `RATE_LIMIT_TRUST_XFF=1`,
`AI_PROVIDER`, `IMAGE_PROVIDER`, `VOICE_PROVIDER`, optional `GEMINI_*_MODEL` pins,
`META_APP_ID`, `META_GRAPH_VERSION`, `META_ES_CONFIG_ID`, `META_ADVANCED_ACCESS`,
`PLATFORM_DOMAIN` (only with a custom domain), `AI_SANDBOX_ENABLED` (default on).

**locah-worker** — secrets: `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`GEMINI_API_KEY`, `WEBSITE_PREVIEW_SECRET`, `WEB_REVALIDATE_SECRET`. Config:
`ENVIRONMENT=production`, `SUPABASE_URL`, `AI_PROVIDER`, `IMAGE_PROVIDER`,
`VOICE_PROVIDER`, `WORKER_POLL_INTERVAL_SECONDS`, `WEB_REVALIDATE_URL`
(`https://<web host>/api/revalidate`).

**locah-web** — public build variables: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WEB_URL`,
`NEXT_PUBLIC_WORKSPACE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
`NODE_ENV=production`; server-only: `REVALIDATE_SECRET` (same value as the worker's
`WEB_REVALIDATE_SECRET`; it can only clear a cached page).

**locah-workspace** — the same public build variables as web; no server secrets.

Never set in production: `LOCAH_TEST_NO_EXTERNAL_AI`, `MESSAGING_SANDBOX`,
`AUTO_GENERATE_WEBSITE_IMAGES`, `*_REPLAY_FILE`, any `XAI_*`. Never put a server
secret under `NEXT_PUBLIC_*`.

## Release procedure

1. **Database first.** Apply only migrations the hosted history lacks
   (`npx supabase db push` from `infra/`, after a schema comparison), then the
   idempotent seed: `psql "$DATABASE_URL" -f infra/supabase/seed/00_platform.sql`.
   Migrations are forward-only; never edit one that has been applied.
2. **`main` points at the tested commit** (CI green).
3. Railway builds the services from that commit — API and worker first, then web
   and Workspace.
4. **Smoke test the deployed URLs:** `/health/live`, `/health/ready`
   (`database: connected`), worker logs, sign-in on web and Workspace, one business
   created through Talk to Locah, its website built and published, one order, one
   booking.

**Rollback:** redeploy the previous successful deployment of the affected service
in Railway (or revert the commit on `main`). Migrations are not rolled back;
write a new forward migration instead.

## Supabase Auth

- URL configuration: Site URL = the production web origin; Redirect URLs = the web
  and Workspace origins (`https://<host>/**`). Use local Supabase for local tests;
  never set the production Site URL to localhost.
- Sign-up and sign-in use emailed **8-digit codes**. The *Confirm signup* and
  *Magic Link* templates must contain `{{ .Token }}` — paste
  `infra/supabase/email-templates/src/confirm-signup.html` and `magic-link.html`
  (details in that folder's README). Email OTP length 8, expiry 600 s.
- Configure a verified sending domain and custom SMTP for production delivery.
  On the hosted Free plan, SMTP is also required to edit the email templates.
  Repository templates and Railway deploys do not update hosted Auth settings.
- Password reset is still a link and lands on `/auth/update-password`.

## External activations (not live yet)

- **Online payments:** merchant onboarding and live keys for the payment provider;
  until then pay at pickup / on delivery works and online payment is unavailable.
- **WhatsApp:** Meta Tech Provider enrolment, App Review advanced access
  (`META_ADVANCED_ACCESS=1`), Embedded Signup (`META_ES_CONFIG_ID`), webhook
  subscription with `META_APP_SECRET` / `WHATSAPP_VERIFY_TOKEN`. Until both secrets
  are set the webhook routes answer 404.
- **Custom domain:** `<domain>` web, `app.<domain>` Workspace, `api.<domain>` API,
  `{slug}.<domain>` tenant sites; set `PLATFORM_DOMAIN` / `NEXT_PUBLIC_PLATFORM_DOMAIN`,
  update Supabase URL configuration, regenerate templates
  (`PLATFORM_DOMAIN=<domain> pnpm email:templates`).
