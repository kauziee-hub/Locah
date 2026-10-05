# LOCAH auth emails and redirect configuration

These are the transactional emails Supabase sends on signup, invite, magic link,
password reset, email change and reauthentication. They are checked in here because Supabase stores
templates and URL settings in project configuration, not in the repository — there
is no migration that can apply them, and no service-role API that can set them.
They have to be pasted into the dashboard once per project.

## 0. Sign-up and sign-in are by emailed code (October 2026)

Creating an account and signing in no longer depend on clicking a link. The
person enters their email, LOCAH emails an **8-digit code**, and they type it on
the page they already have open (`apps/web/src/app/login/LoginForm.tsx`, the
Workspace's `EmailCodeSignIn`, the invitation join page; shared logic in
`packages/auth/src/email-otp.ts`). Supabase sends the code with
`signInWithOtp` and checks it with `verifyOtp({ type: 'email' })`; the session
cookie is set by `@supabase/ssr` exactly as before.

Supabase uses **two** templates for this, so both must show `{{ .Token }}`:

| Template (dashboard) | When Supabase sends it | File | Subject |
| --- | --- | --- | --- |
| Confirm signup | the address has no account yet | `confirm-signup.html` | Your LOCAH code |
| Magic Link | the address already has an account | `magic-link.html` | Your LOCAH sign-in code |

Both are code-only — no link, no origin to render — so they can be pasted from
`src/` directly. Also set, under Authentication → Providers → Email:
**Email OTP Length = 8** and **Email OTP Expiration = 600** seconds (matching
`infra/supabase/config.toml`).

Password sign-in still works for accounts that have a password, and password
**reset** is still a link (`reset-password.html`), so §1 below still matters for
that one email.

## The bug this fixes

A confirmation email pointed at `http://localhost:3000`, so clicking it produced
"site can't be reached".

The cause is not in the application. Supabase validates the `emailRedirectTo` that
`signUp()` sends against the project's **Redirect URLs** allowlist, and when there
is no match it *silently substitutes Site URL* rather than failing. Verified
against this project:

```
request : redirect_to=https://locah-web-production.up.railway.app/auth/callback
returned: redirect_to=http://localhost:3000
```

So Site URL was `http://localhost:3000` and the production callback was not
allowlisted. **No application change can override this** — the settings below are
what actually fix it.

## 1. URL configuration

Authentication → URL Configuration:

| Setting | Value |
| --- | --- |
| Site URL | `https://locah-web-production.up.railway.app` |
| Redirect URLs | `https://locah-web-production.up.railway.app/**`<br>`https://locah-workspace-production.up.railway.app/**` |

Site URL is what a link falls back to, so it must be the production web app.
Use local Supabase for local signup testing. Production does not need a localhost
redirect entry, and localhost must never be the production Site URL.

When a custom domain replaces Railway's generated domains, update Site URL and
add the new web and Workspace origins here.

## 2. Email templates

Authentication → Email Templates. Paste each file into the matching template and
set the subject:

| Template | File | Subject |
| --- | --- | --- |
| Confirm signup | `confirm-signup.html` | Your LOCAH code |
| Invite user | `invite.html` | You have been invited to LOCAH |
| Magic Link | `magic-link.html` | Your LOCAH sign-in code |
| Change Email Address | `change-email.html` | Confirm your new email |
| Reauthentication | `reauthentication.html` | Your LOCAH verification code |
| Reset Password | `reset-password.html` | Reset your LOCAH password |

### Security notifications

Authentication → Emails → Security. All seven are switched on in the **Locah**
project; each has its own template. They carry **no link** (a "click here" in a
security email looks like phishing) and no origin, so they are rendered like the
code-only emails and can be pasted from `dist/` as they are.

| Notification | File | Subject | Variables it uses |
| --- | --- | --- | --- |
| Password changed | `password-changed.html` | Your LOCAH password was changed | `.Email` |
| Email address changed | `email-changed.html` | Your LOCAH email address was changed | `.OldEmail`, `.Email` |
| Phone number changed | `phone-changed.html` | Your LOCAH phone number was changed | `.OldPhone`, `.Phone`, `.Email` |
| Sign-in method linked | `identity-linked.html` | A sign-in method was added to your LOCAH account | `.Provider`, `.Email` |
| Sign-in method removed | `identity-unlinked.html` | A sign-in method was removed from your LOCAH account | `.Provider`, `.Email` |
| MFA method added | `mfa-enrolled.html` | A verification method was added to your LOCAH account | `.FactorType`, `.Email` |
| MFA method removed | `mfa-unenrolled.html` | A verification method was removed from your LOCAH account | `.FactorType`, `.Email` |

The variable names are Supabase's own (see "Template variables" in
https://supabase.com/docs/guides/local-development/customizing-email-templates).

## 3. Why these use `{{ .TokenHash }}`

Supabase's default templates use `{{ .ConfirmationURL }}`, which points at
`https://<project>.supabase.co/auth/v1/verify?...`. That is the address the
recipient sees hovering the button — a Supabase URL in an email claiming to be
from LOCAH, which is exactly the shape of a phishing link.

These templates instead send `{{ .TokenHash }}` to `{{ .SiteURL }}/auth/confirm`,
handled by `apps/web/src/app/auth/confirm/route.ts`. The visible link is LOCAH's
own domain and the redirect no longer depends on Supabase's Site URL fallback.

`/auth/callback` still handles the `?code=` flow, so reverting a template to the
Supabase default will not break sign-in.

## 4. Verifying

After changing the settings, confirm the link is right without sending mail:

```bash
curl -s "$SUPABASE_URL/auth/v1/admin/generate_link" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type":"signup","email":"probe@example.com","password":"<throwaway>",
       "options":{"redirect_to":"https://locah-web-production.up.railway.app/auth/callback"}}'
```

`redirect_to` in the returned `action_link` must come back as the URL that was
requested. If it comes back as something else, the allowlist still does not match.

`generate_link` creates the user, so delete it afterwards:
`DELETE /auth/v1/admin/users/<id>` with the same headers.

## 5. Sender identity

LOCAH's auth emails are sent from **`LOCAH <no-reply@auth.locah.store>`**.

* Sending domain `auth.locah.store` is verified in Resend (region ap-northeast-1,
  open and click tracking **off** — rewritten links damage code emails).
  A subdomain keeps sign-in mail's reputation apart from the root domain, which
  stays free for a future mailbox.
* Nothing reads replies: Resend receiving is off and there is no mailbox, and the
  emails say so. Add a monitored address before promising one in these emails.
* The app itself sends no email (there is no SMTP or Resend code in it); Supabase
  Auth sends all of it. **Railway needs no mail variables.**

DNS in the Hostinger zone for `locah.store` (the apex `@` and `www` records are
untouched):

| Type | Name | Value |
| --- | --- | --- |
| TXT | `resend._domainkey.auth` | `p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDx6LfdVru40bk/eQuN9Fgetyh63ht0QerJnlDsm9FjU0qauyZ63Hvys5+nC9IfNM6kBvxEZxx/zzU7p6doHAsKGShjKZnhtFOJsPlQ+8zv4C5oKsoeB5i5hXaB9lHwLQFRmcLV0VJMK9aY+m4vOuNdpBatWDDZ9D13Jxs0OoMwlQIDAQAB` (DKIM) |
| MX | `send.auth` | `10 feedback-smtp.ap-northeast-1.amazonses.com` (bounces) |
| TXT | `send.auth` | `v=spf1 include:amazonses.com ~all` (SPF) |
| CNAME | `rsend.auth` | `send.forge.rmta.net` |
| TXT | `_dmarc` | `v=DMARC1; p=none; adkim=r; aspf=r` (monitor only) |

DMARC starts at `p=none`. After a few weeks of clean sending, tighten it to
`p=quarantine`.

## 6. Connecting it to Supabase

Done in Authentication → Emails of the **Locah** project (the SMTP password is a
secret, so it is entered there by hand — never in Git, chat or a public variable):

1. In Resend → API Keys, create a key named `supabase-auth-smtp` with **Sending
   access** limited to the domain `auth.locah.store`.
2. SMTP Settings → enable custom SMTP:
   host `smtp.resend.com`, port `465`, username `resend`, password = that key,
   sender email `no-reply@auth.locah.store`, sender name `LOCAH`.
3. Templates: paste the thirteen rendered files from `dist/` (six sign-in and
   account emails plus seven security notifications, see §2) with their
   subjects. Render with
   `node tools/render-email-templates.mjs --origin https://locah-web-production.up.railway.app`
   (use the custom origin instead once `locah.store` serves the web app).
4. Authentication → Providers → Email: OTP length **8**, expiry **600** seconds.
5. Check delivery for real: sign up and sign in with a test address, and look at
   the inbox (and spam). An accepted OTP request alone is not proof of delivery.

If sign-in answers "We could not do that just now", read Supabase's auth log for
the request (`/otp`, status 500). `gomail: could not send email 1: 550 "This API key
is not authorized to send emails from locah.store"` means the **sender email** in
Authentication -> Emails -> SMTP Settings is on `locah.store` while the Resend key is
limited to `auth.locah.store`. It must be `no-reply@auth.locah.store`.

The templates' header is built from table cells and text — an orange tile with a
white "L." and the LOCAH wordmark — so it renders in every mail app. Gmail strips
SVG, and remote images are blocked by default in several clients. The logo files
(SVG and PNG) are in `apps/web/public/brand/`.

Official setup: https://resend.com/docs/send-with-supabase-smtp and
https://supabase.com/docs/guides/auth/auth-smtp. Do not enable an incomplete SMTP
configuration: it will prevent auth emails from being sent.

## 7. Main domain: `locah.store`

The web service (`locah-web`) in Railway has `locah.store` attached as its custom
domain. It serves over HTTPS with its own certificate (verified 2026-10-05). The
Railway plan allows **one custom domain per service**, so `www.locah.store` is not
served by Railway, and the single slot on `locah-web` is the apex, so a wildcard
for `{slug}.locah.store` Business websites is not possible on this plan.

DNS in the Hostinger zone:

| Type | Name | Value |
| --- | --- | --- |
| TXT | `_railway-verify` | `railway-verify=...` (Railway ownership check) |
| ALIAS | `@` | `satsmdln.up.railway.app` (CNAME flattening; the parked `A` record was deleted by hand because the DNS connector cannot delete records) |

Railway keeps listing the apex as "requires update" because it looks for a literal
CNAME; the certificate is valid and the site loads, so that line can be ignored.

Supabase Site URL is `https://locah.store` with both origins in Redirect URLs.

### `www.locah.store`

Railway allows one custom domain per service and `locah-web` uses it for the apex,
so `www` is served by a separate tiny service, **`locah-www-redirect`** (the official
`caddy:2-alpine` image). Its `CADDYFILE` variable is written to `/tmp/Caddyfile` by
the start command and answers every request on port 8080 with
`redir https://locah.store{uri} permanent` (301, path and query kept). Hostinger has
`www` as a CNAME to that service and `_railway-verify.www` as its ownership TXT.
Railway terminates TLS for `www` with its own Let's Encrypt certificate and sends
`http://` to `https://` before Caddy sees it. Remove the service and the two `www`
records together if `locah-web` ever gets a second domain slot.

A change to a service's start command does not take effect on `redeploy` (it reuses
the existing build); set or change a variable to force a fresh deployment.

### The switch (2026-10-05)

`locah.store` is the web app's main address:

* `locah-api` `CORS_ALLOWED_ORIGINS` is
  `https://locah-web-production.up.railway.app,https://locah-workspace-production.up.railway.app,https://locah.store`
  (the first two were the live value, inferred from preflight probes because
  Railway hides variable values from the connector; the third is new).
* `locah-web` and `locah-workspace` have `NEXT_PUBLIC_WEB_URL=https://locah.store`
  and were rebuilt (the Dockerfile declares it as a build argument).
  Workspace now sends signed-out visitors to `https://locah.store/login`.

The link emails (Invite, Change Email, Reset Password) **must** carry the same
origin as `NEXT_PUBLIC_WEB_URL`. `apps/web/src/app/auth/confirm/route.ts` ends with
`NextResponse.redirect(siteUrl(destination))`, and `siteUrl` reads
`NEXT_PUBLIC_WEB_URL`. If a template used a different host, the token would verify
and set the session cookie there, then redirect to the other host, which has no
such cookie, and the person would land signed out. Render with
`node tools/render-email-templates.mjs --origin https://locah.store` and paste all
three. Emails sent before the switch with the Railway origin will verify but
land signed out; request a fresh one.

`NEXT_PUBLIC_PLATFORM_DOMAIN` must stay unset on this plan: it makes
`businessSiteUrl()` return `https://{slug}.locah.store`, which does not resolve.
Workspace and the API remain on their Railway addresses; moving them to
`app.locah.store` and `api.locah.store` needs `NEXT_PUBLIC_WORKSPACE_URL`,
`NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_SESSION_COOKIE_DOMAIN=locah.store`, a
custom domain on each service (one allowed per service on this plan) and a CORS
update.
