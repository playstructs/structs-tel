# UPGRADE — directory listing, QR device linking, fleet rooms

Operator guide to bring an **existing** structs-tel Matrix deploy up to this feature set.
For a greenfield install, follow [SETUP.md](SETUP.md) (templates already include these defaults), then the fleet/guild-bot sections below.

Crew.oh.energy is the reference implementation; failure diary lives in [CREW-REFERENCE.md](CREW-REFERENCE.md). This file is the clean replicate path.

## Prerequisites

- Synapse + MAS running and joined to the guild Docker network
- Webapp OIDC working (discovery + JWKS 200)
- Applied webapp fixes from [STRUCTS-WEBAPP-HANDOFF.md](STRUCTS-WEBAPP-HANDOFF.md) if you hit `invalid claim "exp"` or unreadable `private.key`
- Shell access as the compose user; ability to restart Caddy if you terminate TLS there

## 1. Sync this repo and re-render

```bash
cd ~/structs-tel   # or your checkout
# pull / rsync latest structs-tel
./scripts/render-configs.sh
grep -E 'enable_room_list_search|msc4108' config/synapse/homeserver.yaml
```

Expect:

```yaml
enable_room_list_search: true
room_list_publication_rules:
  - user_id: "@guild-bot:<MATRIX_SERVER_NAME>"
    action: allow
  - action: deny
experimental_features:
  msc4108_enabled: true
```

Without `room_list_publication_rules`, Synapse refuses directory publication (`Not allowed to publish room`) even for room creators.

## 2. Guild-bot (once per homeserver)

Room v12 creators have permanent infinite power. **All guild and fleet rooms must be created by `@guild-bot`**, not by players.

```bash
cd ~/structs-tel
docker compose exec -T mas mas-cli manage register-user -y --no-admin \
  -d "Guild Bot" guild-bot
# Ignore "already exists" if re-running

TOKEN=$(docker compose exec -T mas mas-cli manage issue-compatibility-token guild-bot \
  2>&1 | grep -oE 'mct_[A-Za-z0-9._-]+' | head -1)
umask 077
mkdir -p config/secrets
printf '%s\n' "$TOKEN" > config/secrets/guild-bot.compatibility-token
chmod 600 config/secrets/guild-bot.compatibility-token
```

Never commit the token. Export `GUILD_BOT_TOKEN` if you prefer env over the file.

## 3. Recreate Synapse (pick up template flags)

```bash
docker compose --profile init run --rm synapse-fix-perms   # if media_store permission issues
docker compose up -d --force-recreate synapse
sleep 5
curl -sS http://127.0.0.1:${SYNAPSE_CLIENT_PORT:-8008}/_matrix/client/versions \
  | jq '.unstable_features["org.matrix.msc4108"]'
# expect: true
```

## 4. Caddy / reverse proxy

Confirm:

| Host | Proxies to | Must include |
|---|---|---|
| `auth.<guild>` | MAS (`127.0.0.1:8081`) | `/device`, `/link`, `/authorize`, `/upstream/…` |
| `matrix.<guild>` | Synapse (`127.0.0.1:8008`) | `/_matrix/…`, `/_synapse/client/rendezvous`, well-known |

See [config/caddy/Caddyfile.example](../config/caddy/Caddyfile.example).

If `admin off` is set (crew), use `systemctl restart caddy` — not `reload`.

Do **not** URI-decode federation paths (no Apache without `nocanon`; nginx `proxy_pass` must not append a URI path). See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## 5. Verify channel listing

Rooms need `visibility: "public"` (and usually a canonical alias) to appear in Element Explore.

```bash
TOKEN=$(cat config/secrets/guild-bot.compatibility-token)
curl -sS -X POST "http://127.0.0.1:8008/_matrix/client/v3/publicRooms" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit":50}' | jq '.chunk[] | {name,canonical_alias,room_id}'
```

Element: homeserver → Explore rooms. Expect guild public rooms (e.g. `#orbital-hydro:…`).

## 6. Verify QR device linking (MSC4108)

1. Log into Element Web on device A via wallet OIDC (first session).
2. Element → settings → Sessions → **Link new device** / show QR.
3. Scan with Element X (or second client) on device B.
4. Confirm on device A (MAS `/device` or `/link` UI).

If Element says QR is unsupported or rendezvous 404s:

- Confirm `org.matrix.msc4108` is `true` on `/_matrix/client/versions`
- Confirm rendezvous hits **Synapse**, not MAS
- Confirm `auth.` serves MAS `/device` and `/link`

**Fallback (no E2EE secret transfer):** deep-link the new device through the same OIDC authorize / `/?oidc=…` wallet login. Documented in USAGE.md.

## 7. Fleet public rooms

Convention:

| Field | Value |
|---|---|
| Alias | `#fleet-{fleetId}` e.g. `#fleet-9-42:matrix.example` |
| Fleet id | `9-{playerIndex}` (player Matrix user is `@1-{playerIndex}:…`) |
| Creator | `@guild-bot` |
| Visibility / join | `public` / `public` |
| Owner power | player MXID at PL 100 |

Ensure one room (idempotent):

```bash
export MATRIX_SERVER_NAME=matrix.crew.oh.energy   # your server_name
python3 scripts/ensure-fleet-room.py --player-id 1-42
# or: --fleet-id 9-42
```

Backfill (example loop):

```bash
for pid in 1-1 1-2 1-42; do
  python3 scripts/ensure-fleet-room.py --player-id "$pid" || true
done
```

Hybrid model: run ensure after first Matrix login (ops script or future webapp hook — see STRUCTS-WEBAPP-HANDOFF). Do **not** let players create these rooms themselves (v12 creator trap).

## 8. Rollback

| Change | Rollback |
|---|---|
| Synapse flags | Remove `enable_room_list_search` / `experimental_features` from template (or set `msc4108_enabled: false`), re-render, recreate Synapse |
| Fleet / guild rooms | Leave in place (safe). Delete via Admin API only if intentional |
| Guild-bot account | Leave; demote/lock only if compromised — rotate compatibility token |
| Caddy | Restore previous Caddyfile backup; `systemctl restart caddy` |

## Checklist

- [ ] `homeserver.yaml` has `enable_room_list_search: true`, `msc4108_enabled: true`, and `room_list_publication_rules` allowing `@guild-bot`
- [ ] `/_matrix/client/versions` → `org.matrix.msc4108: true`
- [ ] `@guild-bot` exists; token file present and mode `600`
- [ ] `POST /publicRooms` returns expected public rooms
- [ ] `auth.` → MAS; `matrix.` → Synapse (rendezvous not stolen)
- [ ] Element Explore lists public rooms
- [ ] QR device-link smoke test OK (or fallback documented for this guild)
- [ ] At least one `#fleet-9-N` ensured and joinable

## Related docs

- [SETUP.md](SETUP.md) — greenfield
- [USAGE.md](USAGE.md) — admin, guild-bot, room conventions
- [STRUCTS-WEBAPP-HANDOFF.md](STRUCTS-WEBAPP-HANDOFF.md) — OIDC token/key fixes + optional fleet ensure hook
- [CREW-REFERENCE.md](CREW-REFERENCE.md) — crew diary
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — federation signature / proxy URI decoding
