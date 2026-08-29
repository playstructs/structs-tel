# Go-live checklist

Print or copy. Check every box before calling Matrix chat “up.”

## A. Guild prerequisites

- [ ] `structs-pg` healthy; OIDC Sqitch changes deployed (`oidc_*` tables exist)
- [ ] `structs-webapp` image/source includes OIDC provider
- [ ] Guild Docker network name known (e.g. `docker-structs-guild_default`)
- [ ] Public HTTPS for webapp issuer works in a browser

## B. Secrets and config (this repo)

- [ ] `.env` filled from `.env.example`
- [ ] `./scripts/generate-secrets.sh` run (or equivalent)
- [ ] `MAS_UPSTREAM_PROVIDER_ID` is a real ULID (stable forever for this guild)
- [ ] `./scripts/render-configs.sh` produced `config/synapse/homeserver.yaml` and `config/mas/config.yaml`
- [ ] `config/secrets/signing.key` exists and is mounted into Synapse

## C. Databases

- [ ] `docker compose --profile init run --rm matrix-db-init` succeeded
- [ ] `\l` shows databases `synapse` and `mas` on structs-pg

## D. Matrix services

- [ ] `docker compose up -d` — `structs-matrix` and `structs-mas` healthy/running
- [ ] `curl -sS http://127.0.0.1:8008/_matrix/client/versions` returns JSON
- [ ] MAS listens on configured port (default `127.0.0.1:8081`)

## E. Webapp OIDC

- [ ] OIDC keys generated on webapp (`app:oidc:generate-key` if needed)
- [ ] `OIDC_ENABLED=true`, `OIDC_ISSUER` matches public webapp URL (no trailing slash)
- [ ] `curl -sS https://<webapp>/.well-known/openid-configuration | jq .issuer`
- [ ] `curl -sS https://<webapp>/oauth/jwks | jq '.keys[0].kid'`

## F. Link MAS ↔ webapp

- [ ] MAS upstream provider id matches `MAS_UPSTREAM_PROVIDER_ID`
- [ ] Exact callback URL noted: `https://<mas-host>/upstream/callback/<provider-id>`
- [ ] Webapp seeded: `bin/console app:oidc:seed-client` with that redirect URI + same client secret as MAS
- [ ] Trailing slash on redirect URI matches exactly (first failure is usually this)

## G. Reverse proxy / discovery

- [ ] `https://<matrix-host>/.well-known/matrix/client` advertises homeserver + auth issuer (MAS)
- [ ] `https://<server_name>/.well-known/matrix/server` (or delegation) points at federation
- [ ] Client API and MAS reach browsers over HTTPS
- [ ] Federation port 8448 reachable if you federate

## H. Smoke test

- [ ] Element (or Element X) can complete login via Structs
- [ ] Resulting Matrix ID localpart equals `player.id` (e.g. `@1-42:...`)
- [ ] Second login with existing webapp session is silent / near-silent
- [ ] Cold browser still completes (wallet SPA resume) or blocker documented

## I. Directory / QR / fleet (day-2)

- [ ] `@guild-bot` registered; `config/secrets/guild-bot.compatibility-token` mode `600`
- [ ] `/_matrix/client/versions` → `org.matrix.msc4108: true`
- [ ] Public rooms appear via `POST /publicRooms` / Element Explore
- [ ] At least one `#fleet-9-N` ensured via `scripts/ensure-fleet-room.py` (or backfill planned)
- [ ] Full replicate path: [UPGRADE.md](UPGRADE.md)

## J. Handoff / ops

- [ ] [CREW-REFERENCE.md](CREW-REFERENCE.md) or your guild’s diary updated
- [ ] [DOCKER-STRUCTS-GUILD-HANDOFF.md](DOCKER-STRUCTS-GUILD-HANDOFF.md) reviewed if compose integration is desired later
