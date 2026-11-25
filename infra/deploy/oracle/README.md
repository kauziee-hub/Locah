# LOCAH on Oracle Cloud Always Free

One Arm VM runs the API, the worker, the public site (with every business
website) and the Workspace behind Caddy, which handles TLS. The database and
file storage stay on Supabase (Mumbai, ap-south-1). Cost: nothing within
Oracle's Always Free allowance (Arm A1: 4 OCPUs, 24 GB memory, 200 GB of block
storage in total per account).

Steps marked **you** need the account owner: a sign-in, a card, a secret or a
DNS change. Everything else is in this folder.

## 1. Account (you)

- Home region **India West (Mumbai)**: closest to Supabase ap-south-1. It
  cannot be changed later.
- Optional but recommended: upgrade to Pay As You Go. Always Free resources stay
  free; a free-tier-only account can have an idle VM reclaimed.

## 2. The VM (you, in the Oracle console)

1. Compute → Instances → Create: image **Ubuntu 24.04** (aarch64), shape
   **VM.Standard.A1.Flex**, 4 OCPU / 24 GB (or as much as Mumbai has capacity
   for; 2 OCPU / 12 GB also works), boot volume 100 GB, your SSH public key,
   a public IPv4 address. Reserve the public IP (Networking → Reserved IPs) so
   it never changes.
2. The instance's subnet → Security List → add ingress rules from `0.0.0.0/0`:
   TCP 80, TCP 443, UDP 443.

## 3. Prepare it

```bash
ssh ubuntu@<public-ip>
git clone https://github.com/kauziee-hub/Locah.git && cd Locah
git checkout main
bash infra/deploy/oracle/setup.sh
exit   # log back in so the docker group applies
```

## 4. Configuration (you, on the VM)

`setup.sh` created `infra/deploy/oracle/public.env` and `server.env` from the
examples (mode 600). Fill them in **on the VM** — over SSH with `nano` — from
the Supabase dashboard and the provider dashboards. Secrets never go into Git,
chat or a ticket. `REVALIDATE_SECRET` is the same value in both files
(`openssl rand -hex 32`).

## 5. Database migrations

The hosted Supabase project must have every migration in
`infra/supabase/migrations` before the new code starts. On 2026-11-25 it was
brought level with `main`: 111 files, 111 history rows, matching by version and
name. Six migrations were applied then (20261017120000, 20261017140000,
20261018120000, 20261018150000, 20261122120000, 20261125090000), and the
`website_experience_layer` row was re-versioned from 20261014052757 to the
file's 20261009120000.

Before starting newer code, compare the folder with
`supabase_migrations.schema_migrations` by version and name. Apply any missing
file together with its history row in one transaction (Supabase SQL editor or
`supabase db push`).

## 6. DNS for locah.store (you, at Hostinger)

Replace the parking record (A `@` → 153.52.255.3) with:

| Type | Name | Value |
|---|---|---|
| A | `@` | VM public IP |
| A | `www` | VM public IP |
| A | `app` | VM public IP |
| A | `api` | VM public IP |
| A | `*` | VM public IP (every business's `{slug}.locah.store`) |

## 7. Start

```bash
cd ~/Locah/infra/deploy/oracle
docker compose --env-file public.env up -d --build   # first build takes ~10 minutes
docker compose ps
curl -fsS https://api.locah.store/health/ready
```

Caddy takes certificates for `locah.store`, `www`, `app` and `api` at start.
A business subdomain gets its own on its first visit, after the API confirms
it is a published site (`/v1/public/tls/allowed`); a made-up name never does.

## 8. Supabase Auth (you)

Authentication → URL configuration: Site URL `https://locah.store`; redirect
URLs `https://locah.store/**` and `https://app.locah.store/**`.

## 9. Retire the old hosts

One job queue lives in the database. Stop any Railway worker (and any local
worker pointed at the hosted database) so two workers never claim the same jobs.

## Updating

```bash
cd ~/Locah && git pull
cd infra/deploy/oracle && docker compose --env-file public.env up -d --build
```

Logs: `docker compose logs -f api worker` · `website.quality_gate` lines are the
shadow quality verdicts; `website.build_over_budget` and `ai.cap_reached` are the
build alerts.
