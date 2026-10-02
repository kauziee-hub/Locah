# LOCAH auth emails and redirect configuration

These are the transactional emails Supabase sends on signup, invite, magic link,
password reset and email change. They are checked in here because Supabase stores
templates and URL settings in project configuration, not in the repository — there
is no migration that can apply them, and no service-role API that can set them.
They have to be pasted into the dashboard once per project.

## 0. Sign-up and sign-in are by emailed code (October 2026)

Creating an account and signing in no longer depend on clicking a link. The
person enters their email, LOCAH emails a **6-digit code**, and they type it on
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
**Email OTP Length = 6** and **Email OTP Expiration = 600** seconds (matching
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
| Redirect URLs | `https://locah-web-production.up.railway.app/**`<br>`https://locah-workspace-production.up.railway.app/**`<br>`http://localhost:3000/**` |

Site URL is what a link falls back to, so it must be the production web app.
Keep the `localhost` entry so local signup still works — it is in the allowlist,
which is checked, not in Site URL, which is the fallback.

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

The default sender is `noreply@mail.app.supabase.io`, which does not say LOCAH and
carries Supabase's sending reputation. Configuring SMTP under Authentication →
Emails with a LOCAH sending domain (and its SPF/DKIM records) is what makes these
emails actually come *from* LOCAH. Until then the templates are branded but the
envelope sender is not.
