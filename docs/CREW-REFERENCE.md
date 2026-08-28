# CREW-REFERENCE — OrbitalHydro / crew.oh.energy

This is the **reference implementation diary**. When you bring up another guild, substitute hostnames but keep the same order of operations.

Update this file whenever we change something on crew.

## Host layout (observed)

```text
ssh root@crew.oh.energy
su - docker

/home/docker/docker-structs-guild/   # compose project
/home/docker/structs-webapp/         # WEBAPP_SOURCE=../structs-webapp/src
# place structs-tel checkout alongside, e.g.:
/home/docker/structs-tel/
```

- Hostname: `crew.oh.energy`
- Moniker: `OrbitalHydro` (from guild `.env`)
- Docker network: `docker-structs-guild_default`
- Public webapp: `https://crew.oh.energy` (Caddy → nginx/PHP)
- API cache nginx also on `127.0.0.1:8080` (internal)

## Baseline before Matrix (2026-08-28)

### Running services

Including: `structs-pg`, `structs-webapp`, `structsd`, nats, grass, crawler, tsa, sync-state, webapp-cache.

### OIDC on webapp

- Code present: `OidcController`, `app:oidc:generate-key`, `app:oidc:seed-client`, `src/src/Oidc/`, docs under `structs-webapp/docs/matrix-oidc-*-handoff.md`
- `~/structs-webapp/src/.env` had `OIDC_ENABLED=false` →  
  `curl https://crew.oh.energy/.well-known/openid-configuration` returned **Symfony 404**
- OIDC env keys already stubbed (`OIDC_MAS_CLIENT_ID=matrix-auth-service`, JWT paths, encryption key placeholder)

### Postgres

- Image: `structs/structs-pg:latest`
- Sqitch deployed OIDC changes:
  - `table-oidc-20260826-provider`
  - `role-structs-webapp-20260826-oidc`
- `pg_hba`: `hostssl` **trust** for `structs` / `structs_webapp` / indexer / crawler on database **`structs` only**; other DBs use **md5**
- Implication: Matrix DBs `synapse`/`mas` must use **password** roles (init script does this; `PGSSLMODE=require`)

### Guild compose

- Does **not** yet include Synapse/MAS (by design — this repo stays separate; handoff later)
- Webapp env: `DATABASE_URL=postgres://structs_webapp@structs-pg:5432/structs?serverVersion=17` (no password)

## Planned bring-up sequence on crew

Track checkboxes as we execute:

- [x] Clone/copy `structs-tel` to `/home/docker/structs-tel`
- [x] Write `.env` with crew hostnames + ULID provider id
- [x] Secrets + signing key + `mas-secrets.yaml`
- [x] `./scripts/render-configs.sh`
- [x] `docker compose --profile init run --rm matrix-db-init`
- [x] Fix Synapse volume perms + `docker compose up -d`
- [x] Enable webapp OIDC (keys, issuer, seed)
- [x] Verify discovery + JWKS on `https://crew.oh.energy`
- [x] DNS A records for `matrix.crew.oh.energy` + `auth.crew.oh.energy` (both → `155.138.156.195`)
- [x] Configure Caddy for matrix/auth hosts + well-known
- [ ] Element smoke test; confirm `@<player.id>:matrix.crew.oh.energy`
- [x] Record failures/fixes below

## Command cheat sheet (crew)

```bash
ssh root@crew.oh.energy
su - docker

docker network ls | grep struct
docker ps --format 'table {{.Names}}\t{{.Status}}' | head

# Webapp env / OIDC
grep ^OIDC_ ~/structs-webapp/src/.env | grep -v SECRET | grep -v ENCRYPTION
curl -sS https://crew.oh.energy/.well-known/openid-configuration | jq .issuer

# Matrix stack
cd ~/structs-tel
docker compose ps
docker compose logs -f mas synapse
curl -sS https://matrix.crew.oh.energy/_matrix/client/versions | jq .versions[0]
curl -sS https://matrix.crew.oh.energy/.well-known/matrix/client | jq .
curl -sS -o /dev/null -w '%{http_code}\n' https://auth.crew.oh.energy/
```

## Failures and fixes

| When | Symptom | Fix |
|---|---|---|
| 2026-08-28 survey | Discovery 404 | Expected — `OIDC_ENABLED=false` |
| 2026-08-28 survey | `psql -U structs_webapp` password prompt on localhost | Use Docker network + SSL + correct DB; trust is hostssl to `structs` DB |
| 2026-08-28 bring-up | Synapse `PermissionError: /data/media_store` | Volume root-owned; `docker compose --profile init run --rm synapse-fix-perms` (chown 991:991) |
| 2026-08-28 bring-up | MAS `missing field secrets` | Generate `config/secrets/mas-secrets.yaml` via `mas-cli config generate`; inject at render |
| 2026-08-28 bring-up | MAS YAML “more than one document” | Secrets marker must not appear inside comments (`MAS_SECRETS_BLOCK_GOES_HERE` alone on a line) |
| 2026-08-28 bring-up | Synapse collation `C.UTF-8` vs `C` | Set `allow_unsafe_locale: true` in homeserver DB config |
| 2026-08-28 bring-up | MAS DB `UnsupportedCertVersion` | `structs-pg` had X.509 **v1** server cert; rustls needs **v3**. Regenerated cert from existing key under `/etc/postgresql/18/main/server.crt` (backup `server.crt.v1.bak`), restarted postgres |
| 2026-08-28 bring-up | MAS metadata warmup 404 | Webapp OIDC still off; fixed after enabling OIDC + restart |
| 2026-08-28 bring-up | Shell mangled ULID in callback (`\017` octal) | Prefer Python helpers (`crew-enable-webapp-oidc.py`, `crew-seed-and-verify-oidc.py`) over bash stringing ULIDs |
| 2026-08-28 Caddy | `systemctl reload caddy` fails: `localhost:2019 connection refused` | Global block has `admin off`; use `systemctl restart caddy` after Caddyfile edits |
| 2026-08-28 Caddy | DNS ready for matrix/auth | LE certs issued; HTTPS probes OK |
| 2026-08-28 Element | `/oauth/authorize` → 500 | `config/oidc/private.key` was `root:600` after `app:oidc:generate-key`; `chown www-data` + `chmod 640`. Authorize now 302 → `/?oidc=<id>` (wallet login resume) |
| 2026-08-28 Element | MAS callback `invalid claim "exp"` | `lcobucci/jwt` emitted fractional `iat`/`exp`; MAS requires integer NumericDate. Patched `IdTokenResponse.php` to `setTimestamp(...)` (see `scripts/crew-fix-id-token-numericdate.py`) |

## Final working shape

```text
OIDC_ISSUER=https://crew.oh.energy
MATRIX_SERVER_NAME=matrix.crew.oh.energy
MAS_PUBLIC_BASE=https://auth.crew.oh.energy/
MAS_UPSTREAM_PROVIDER_ID=0177021905F7F7F77B13E10BC9
Public probes: matrix versions 200, auth discovery 200, well-known OK
Element login: pending manual smoke test
Matrix MXID example: pending
Notes: structs-pg TLS cert must stay X.509 v3 for MAS; Caddy admin off → restart not reload
```
