# SETUP — stand up Matrix chat for a Structs guild

Follow in order. For a worked example, keep [CREW-REFERENCE.md](CREW-REFERENCE.md) open and mirror substitutions for your hostnames.

## 0. Prerequisites

1. Guild stack running (`docker-structs-guild` or equivalent).
2. Containers include at least: `structs-pg`, `structs-webapp`.
3. OIDC tables deployed on Postgres (Sqitch `table-oidc-*` / `role-structs-webapp-*-oidc`).
4. Webapp build includes OIDC (`OidcController`, `app:oidc:*` commands).
5. You know the Docker **network name** of the guild compose project:

```bash
docker network ls | grep -i struct
# example: docker-structs-guild_default
```

6. You can reach the webapp over the **public HTTPS issuer** you will put in `OIDC_ISSUER` (browsers and MAS must use this URL, not an internal Docker hostname).

## 1. Clone / place this repo

On the guild host (example layout used on crew):

```text
~/docker-structs-guild/     # existing guild stack
~/structs-webapp/           # webapp source bind-mounted into the stack
~/structs-tel/              # this repo
```

```bash
git clone <this-repo-url> ~/structs-tel
cd ~/structs-tel
cp .env.example .env
```

Set at least:

| Variable | Example |
|---|---|
| `GUILD_DOCKER_NETWORK` | `docker-structs-guild_default` |
| `MATRIX_SERVER_NAME` | `matrix.crew.oh.energy` |
| `SYNAPSE_PUBLIC_BASEURL` | `https://matrix.crew.oh.energy/` |
| `MAS_PUBLIC_BASE` | `https://auth.crew.oh.energy/` |
| `OIDC_ISSUER` | `https://crew.oh.energy` (no trailing slash) |
| `MAS_UPSTREAM_PROVIDER_ID` | new ULID — generate once and never change |

## 2. Generate secrets and Synapse signing key

```bash
./scripts/generate-secrets.sh
# Merge config/secrets/.env.generated into .env
# Ensure MATRIX_SERVER_NAME matches what you passed / will use
```

Produces (all gitignored under `config/secrets/`):

- `signing.key` — Synapse federation signing key (compose mounts this)
- `mas-secrets.yaml` — MAS `secrets:` block (encryption + signing keys); **keep forever**
- `.env.generated` — passwords / shared secrets to merge into `.env`

```bash
ls -l config/secrets/signing.key config/secrets/mas-secrets.yaml
```

## 3. Render Synapse + MAS configs

```bash
./scripts/render-configs.sh
ls config/synapse/homeserver.yaml config/mas/config.yaml
# Confirm rendered MAS config contains a top-level secrets: block
grep -n '^secrets:' config/mas/config.yaml
```

## 4. Create Matrix databases on structs-pg

```bash
docker compose --profile init run --rm matrix-db-init
```

Expected: script prints `synapse` and `mas` databases.

If connection fails:

- Confirm `GUILD_DOCKER_NETWORK` and that `structs-pg` is on that network:  
  `docker network inspect "$GUILD_DOCKER_NETWORK" | grep structs-pg`
- Confirm SSL: init script sets `PGSSLMODE=require` (structs-pg uses `hostssl`).
- Admin user defaults to `structs` on database `structs` (passwordless trust for that pair on many guilds). Set `PGPASSWORD` in `.env` if your admin requires a password.

## 5. Fix Synapse volume ownership, then start

Docker named volumes are root-owned; Synapse runs as uid **991** and must create `/data/media_store`:

```bash
docker compose --profile init run --rm synapse-fix-perms
# equivalent: docker run --rm -v structs-matrix-synapse-data:/data alpine chown -R 991:991 /data

docker compose up -d
docker compose ps
curl -sS http://127.0.0.1:${SYNAPSE_CLIENT_PORT:-8008}/_matrix/client/versions | head
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:${MAS_HTTP_PORT:-8081}/health
```

First boot may take a minute while Synapse migrates its schema.

### Postgres TLS note (MAS)

MAS uses rustls and rejects **X.509 v1** server certificates (`UnsupportedCertVersion`). Synapse/OpenSSL clients are more lenient. Ensure `structs-pg` presents a **v3** cert (check with `openssl x509 -in server.crt -noout -text | grep Version`). See crew diary for a one-off reissue from the existing key.

## 6. Enable webapp OIDC

On the webapp container / bind-mounted source:

1. Generate keys if missing:

```bash
docker exec -it docker-structs-guild-structs-webapp-1 \
  php bin/console app:oidc:generate-key
# Follow command output: mount/persist private+public key paths from OIDC_JWT_*_PATH
# Save OIDC_ENCRYPTION_KEY into webapp .env if printed
```

2. Set webapp `.env` (paths vary; on crew: `~/structs-webapp/src/.env`):

```bash
OIDC_ENABLED=true
OIDC_ISSUER=https://crew.oh.energy
OIDC_MAS_CLIENT_ID=matrix-auth-service
OIDC_MAS_CLIENT_SECRET=<same as this repo .env OIDC_MAS_CLIENT_SECRET>
OIDC_MAS_REDIRECT_URI=   # set after step 7, or pass on seed CLI
OIDC_JWT_PRIVATE_KEY_PATH=config/oidc/private.key
OIDC_JWT_PUBLIC_KEY_PATH=config/oidc/public.key
OIDC_JWT_KEY_ID=structs-oidc-1
OIDC_ENCRYPTION_KEY=<from generate-key>
```

3. Restart webapp. Verify:

```bash
curl -sS https://<webapp-host>/.well-known/openid-configuration | jq .issuer
curl -sS https://<webapp-host>/oauth/jwks | jq '.keys[0] | {kid,kty,alg}'
```

404 ⇒ `OIDC_ENABLED` still false or opcache/old container.  
500 on JWKS ⇒ key path unreadable inside the container.

## 7. Wire MAS upstream ↔ webapp client

MAS config already contains `upstream_oauth2.providers[0].id = MAS_UPSTREAM_PROVIDER_ID`.

Callback URL (exact):

```text
${MAS_PUBLIC_BASE}upstream/callback/${MAS_UPSTREAM_PROVIDER_ID}
```

Example:

```text
https://auth.crew.oh.energy/upstream/callback/01JBEXAMPLE000000000000000
```

Seed the webapp (one guild / one client):

```bash
docker exec -it docker-structs-guild-structs-webapp-1 \
  php bin/console app:oidc:seed-client \
    --client-id=matrix-auth-service \
    --redirect-uri='https://auth.crew.oh.energy/upstream/callback/01JBEXAMPLE000000000000000' \
    --secret="$OIDC_MAS_CLIENT_SECRET"
```

On a single-infra guild, omitting `--guild-id` usually picks `guild_meta.this_infrastructure`. Otherwise pass `--guild-id=...`.

**Redirect URI matching is exact** (scheme, host, path, trailing slash). If login fails immediately, compare seeded URI to MAS callback character-by-character.

Restart MAS after any config render change:

```bash
docker compose up -d mas --force-recreate
```

## 8. Reverse proxy / well-known

Browsers need HTTPS names for Matrix and MAS. Minimal Caddy-style intent:

```caddy
matrix.example {
  reverse_proxy 127.0.0.1:8008
}

auth.example {
  reverse_proxy 127.0.0.1:8081
}

# On the server_name host (or matrix host), serve delegation:
# /.well-known/matrix/server  → {"m.server":"matrix.example:443"}
# /.well-known/matrix/client  → homeserver base_url + MSC2965/auth issuer = MAS public base
```

Example client well-known (adjust names):

```json
{
  "m.homeserver": { "base_url": "https://matrix.crew.oh.energy" },
  "org.matrix.msc2965.authentication": {
    "issuer": "https://auth.crew.oh.energy/",
    "account": "https://auth.crew.oh.energy/account"
  }
}
```

Sample snippets: [config/caddy/](../config/caddy/). Guild proxy integration is described in [DOCKER-STRUCTS-GUILD-HANDOFF.md](DOCKER-STRUCTS-GUILD-HANDOFF.md).

## 9. Smoke test

1. Open Element / Element X.
2. Homeserver: your `MATRIX_SERVER_NAME` or matrix base URL.
3. Continue with OIDC / “Structs Guild Login”.
4. Complete webapp wallet login if prompted.
5. Confirm user ID localpart equals chain **player id** (not wallet address).

Silent path: already logged into the webapp in the same browser → authorize should bounce back quickly.

## 10. Record what you did

Copy commands and outcomes into your guild diary, or append to [CREW-REFERENCE.md](CREW-REFERENCE.md) if this is the reference host. Future you will thank present you.
