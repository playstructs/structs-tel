# TROUBLESHOOTING

## Webapp `/.well-known/openid-configuration` → 404

- `OIDC_ENABLED` is not `true` in the env the **running** container sees.
- Restart webapp after env change; confirm with `docker exec ... printenv OIDC_ENABLED`.

## Webapp `/oauth/jwks` → 500

- Private/public key missing at `OIDC_JWT_*_PATH` inside the container.
- Permissions / bind-mount path wrong.
- Run `php bin/console app:oidc:generate-key` and persist files.

## MAS `/upstream/callback` → 500, webapp `/oauth/token` → `invalid_client`

Wallet login succeeded; MAS then logs:

```text
Request to the token endpoint failed
"invalid_client": Client authentication failed
GET /upstream/callback/<provider-id> → 500
```

MAS uses `token_endpoint_auth_method: client_secret_basic`. RFC 6749 §2.3.1 percent-encodes the secret before Base64. `league/oauth2-server` does **not** urldecode Basic credentials. A secret from `openssl rand -base64 32` often contains `+`, `/`, or `=` (a leading `+` is enough). MAS sends `%2B…`; the webapp hashes a different string → 401.

Confirm (dummy code; 401 means client auth failed, 400 `invalid_grant` means the secret was accepted):

```bash
# RFC-encoded Basic — this is what MAS sends. Must NOT be 401 after a hex rotate.
python3 - <<'PY'
import base64, subprocess
from urllib.parse import quote
from pathlib import Path

def parse(path, key):
    for line in Path(path).read_text().splitlines():
        if line.startswith(key + "="):
            v = line.split("=", 1)[1].strip().strip("'\"")
            return v
    raise SystemExit(f"missing {key}")

secret = parse(".env", "OIDC_MAS_CLIENT_SECRET")
cid = parse(".env", "OIDC_MAS_CLIENT_ID")
issuer = parse(".env", "OIDC_ISSUER").rstrip("/")
rfc = base64.b64encode(f"{quote(cid, safe='')}:{quote(secret, safe='')}".encode()).decode()
subprocess.check_call([
    "curl", "-sS", "-o", "/tmp/oidc-token.body", "-w", "%{http_code}\\n",
    "-X", "POST", f"{issuer}/oauth/token",
    "-H", f"Authorization: Basic {rfc}",
    "-H", "Content-Type: application/x-www-form-urlencoded",
    "-d", "grant_type=authorization_code&code=dummy&client_id=" + cid,
])
print(Path("/tmp/oidc-token.body").read_text()[:300])
PY
```

Fix:

1. `NEW=$(openssl rand -hex 32)` — no `+` `/` `=`
2. Set `OIDC_MAS_CLIENT_SECRET` in **this repo’s `.env` and the webapp `.env`**
3. `php bin/console app:oidc:seed-client` (same secret + existing redirect URI)
4. `./scripts/render-configs.sh` then `docker compose up -d --force-recreate mas`

`./scripts/generate-secrets.sh` and `crew-bootstrap.sh` now emit hex. `./scripts/render-configs.sh` warns if an old base64 secret is still in `.env`. Re-seeding without rotating does nothing.

## MAS or Element: redirect_uri mismatch / immediate failure

- Seeded `OIDC_MAS_REDIRECT_URI` must **exactly** equal  
  `https://<mas-public>/upstream/callback/<provider-ulid>`
- Check trailing slash on `MAS_PUBLIC_BASE` vs callback path.
- Compare DB row in `structs.oidc_client.redirect_uris` to MAS config.

## Login loops back to webapp forever

- Session cookie not sent on `/oauth/authorize` or `/oauth/resume` (`SameSite`, wrong domain, HTTP vs HTTPS).
- Parked OIDC request expired (10 minutes).
- Player not approved for the client’s `guild_id`.
- See webapp infra handoff: cookies blocked → plain-text error on `/oauth/resume`.

## Synapse starts then complains about MAS / auth

- `MAS_SYNAPSE_SHARED_SECRET` differs between rendered homeserver.yaml and mas config.yaml.
- MAS not reachable at `http://structs-mas:8080/` on the guild network.
- Recreate both after re-render.

## `matrix-db-init` cannot connect

- Wrong `GUILD_DOCKER_NETWORK`.
- `STRUCTS_PG_HOST` not resolvable (use `structs-pg` on the shared network).
- SSL required: script sets `PGSSLMODE=require`.
- Admin role lacks `CREATEDB` / ability to `CREATE ROLE`. Use a superuser or grant privileges (guild Postgres ops).

## Matrix localpart is a wallet address / weird id

- Webapp must emit `sub` = `player.id`. If you still see addresses, webapp build is old or claims mapper wrong.
- MAS `claims_imports.localpart.template` must be `{{ user.sub }}`.

## Federation from other servers fails

- Port **8448** closed or not delegated (crew uses well-known → `:443` via Caddy instead).
- `.well-known/matrix/server` missing/wrong.
- TLS certificate problems on federation endpoint.
- Signing key rotated without keeping old keys in `old_verify_keys`.

## `Invalid signature for server matrix.crew.oh.energy with key ed25519:…` when joining a **remote** room

This error is misleading: it usually means the **remote** homeserver failed to verify **our** federation request auth, not that our key file is corrupt.

Synapse signs the request URI **percent-encoded** (`%21`, `%40`, `%3A`). The remote Synapse verifies against `request.uri` as Twisted sees it. If their reverse proxy **decodes** the path before Synapse, verification fails with `BadSignatureError`.

**Check (crew is OK):** through our Caddy, signing the encoded URI works and signing the raw URI fails — encoding is preserved.

**Check (remote is broken):** against the remote, signing the **raw** URI works and signing the **encoded** URI fails — their proxy is decoding.

**Fix:** remote admin must stop URI canonicalization:

- Apache: `ProxyPass … nocanon` (and `AllowEncodedSlashes NoDecode` where needed)
- Nginx: `proxy_pass http://backend;` **without** a URI path after the host (a path forces normalize/decode)
- See [Synapse #3294](https://github.com/matrix-org/synapse/issues/3294) and Synapse reverse-proxy docs

Do **not** patch our Synapse to sign decoded URIs — that breaks correctly configured servers.

Crew example (2026-08-28): joining a room on `matrix.crab.la` failed this way; invite inbound to crew still worked.

## Browse / Explore is empty (`publicRooms` chunk empty)

- Room is `join_rule: public` but was created with `visibility: private` (or never published). Publication is a **separate** flag.
- Only `@guild-bot` may publish (`room_list_publication_rules`). Players and Comms get `Not allowed to publish room`.
- Re-publish as guild-bot: `PUT /_matrix/client/v3/directory/list/room/{roomId}` `{"visibility":"public"}`.
- Other guilds querying `?server=` get `M_FORBIDDEN` unless `allow_public_rooms_over_federation: true`. See [CLIENT-CONTRACT.md](CLIENT-CONTRACT.md).

## Element cannot find auth issuer

- `.well-known/matrix/client` missing `org.matrix.msc2965.authentication` (or current auth discovery key your Element version expects).
- `issuer` must be the **MAS** public base, not the webapp (webapp is upstream of MAS).
