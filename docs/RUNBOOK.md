# RUNBOOK

## Status

```bash
cd ~/structs-tel   # or your checkout
docker compose ps
docker compose logs --tail=100 synapse
docker compose logs --tail=100 mas
```

## Restart

```bash
docker compose restart synapse mas
# or
docker compose up -d --force-recreate synapse mas
```

Config changes (after `./scripts/render-configs.sh`):

```bash
docker compose up -d --force-recreate synapse mas
```

## Re-seed OIDC client

Needed when redirect URI or client secret changes:

```bash
# 1. Update .env OIDC_MAS_CLIENT_SECRET / MAS config; render; recreate mas
# 2. On webapp:
docker exec -it docker-structs-guild-structs-webapp-1 \
  php bin/console app:oidc:seed-client \
    --client-id=matrix-auth-service \
    --redirect-uri='https://auth.<guild>/upstream/callback/<ULID>' \
    --secret='<same secret>'
```

## Rotate MAS ↔ Synapse shared secret

1. Generate new secret; put in `.env` as `MAS_SYNAPSE_SHARED_SECRET`.
2. `./scripts/render-configs.sh`
3. Recreate `synapse` and `mas` together so they never disagree.

## Rotate Synapse signing key

Painful (federation identity). Prefer not to. If you must: follow Synapse docs for old signing keys / `old_signing_keys`, update volume, recreate synapse. Document the key id change in your guild diary.

## Rotate webapp OIDC JWT signing key

Invalidates ID tokens in flight. Update keys on webapp, bump `OIDC_JWT_KEY_ID`, keep old public key in JWKS until tokens expire if your provider supports multiple keys.

## Database backup

Matrix data is **not** in the `structs` database. Backup separately:

```bash
docker exec docker-structs-guild-structs-pg-1 \
  pg_dump -U synapse synapse > synapse-$(date +%F).sql
docker exec docker-structs-guild-structs-pg-1 \
  pg_dump -U mas mas > mas-$(date +%F).sql
```

(Adjust users if your roles need passwords via `PGPASSWORD`.)

Also backup `config/secrets/signing.key` and MAS/Synapse volumes if used for media.

## Disable Matrix for a guild

```bash
docker compose down
# Optionally leave DBs in place for later
# Set OIDC_ENABLED=false on webapp if nothing else uses the IdP
```
