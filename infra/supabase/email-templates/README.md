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
3. Templates: paste the five rendered files from `dist/` (see §2) with their
   subjects. Render with
   `node tools/render-email-templates.mjs --origin https://locah-web-production.up.railway.app`
   (use the custom origin instead once `locah.store` serves the web app).
4. Authentication → Providers → Email: OTP length **8**, expiry **600** seconds.
5. Check delivery for real: sign up and sign in with a test address, and look at
   the inbox (and spam). An accepted OTP request alone is not proof of delivery.

The templates' header is built from table cells and text — an orange tile with a
white "L." and the LOCAH wordmark — so it renders in every mail app. Gmail strips
SVG, and remote images are blocked by default in several clients. The logo files
(SVG and PNG) are in `apps/web/public/brand/`.

Official setup: https://resend.com/docs/send-with-supabase-smtp and
https://supabase.com/docs/guides/auth/auth-smtp. Do not enable an incomplete SMTP
configuration: it will prevent auth emails from being sent.
