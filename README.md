# structs-tel — Structs guild Matrix chat

Standalone **Synapse + Matrix Authentication Service (MAS)** stack for Structs guilds.

Players authenticate with the **existing webapp OIDC provider** (Cosmos signature → session → OIDC). This repo does not implement wallet login; it consumes the webapp issuer.

## Docs map

| Doc | When to read it |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Standing up Matrix for a guild |
| [docs/UPGRADE.md](docs/UPGRADE.md) | Existing deploy → directory listing, MSC4108 QR, fleet rooms |
| [docs/CHECKLIST.md](docs/CHECKLIST.md) | Go-live checkbox list |
| [docs/CREW-REFERENCE.md](docs/CREW-REFERENCE.md) | What we did on `crew.oh.energy` (replicate this) |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Restarts, re-seed, rotations |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Login loops, 404 discovery, JWKS, redirects |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit |
| [docs/DOCKER-STRUCTS-GUILD-HANDOFF.md](docs/DOCKER-STRUCTS-GUILD-HANDOFF.md) | For the guild-compose team (we do not edit that repo) |
| [docs/CLIENT-CONTRACT.md](docs/CLIENT-CONTRACT.md) | What every guild and the game client must implement (directory, presence, encryption, aliases) |
| [OIDC-PROVIDER.md](OIDC-PROVIDER.md) | Webapp OIDC contract (already implemented upstream) |
| [PLANNING.md](PLANNING.md) / [USAGE.md](USAGE.md) | Broader Matrix design / admin notes |

## Prerequisites

- A running guild stack (`docker-structs-guild`) with healthy `structs-pg` and `structs-webapp`
- Webapp OIDC code + `structs-pg` OIDC tables deployed
- Docker network name for the guild project (on crew: `docker-structs-guild_default`)
- DNS/TLS (or local Caddy) for Matrix client URL, MAS URL, and webapp issuer

## Quick start (after reading SETUP)

```bash
cp .env.example .env
# fill secrets — or: ./scripts/generate-secrets.sh && merge config/secrets/.env.generated

./scripts/render-configs.sh
# copy config/secrets/signing.key into place (see SETUP)

docker compose --profile init run --rm matrix-db-init
docker compose up -d

# Then: enable webapp OIDC, create MAS upstream, seed client — see SETUP.md
```

## Important decisions

- **Not** merged into `docker-structs-guild` by this repo — handoff only
- Matrix DBs (`synapse`, `mas`) live on **`structs-pg`**, created by **this** repo’s init script
- OIDC `sub` / Matrix localpart = **`player.id`** (e.g. `@1-42:matrix.example`)
- Public rooms appear in Element Explore / Comms Browse (`enable_room_list_search` + federated directory); QR device linking is MSC4108 via MAS
- Guild/fleet/planet rooms are created by **`@guild-bot`** only (room v12); fleet alias `#fleet-9-N` ↔ player `@1-N` — see [docs/UPGRADE.md](docs/UPGRADE.md) and [docs/CLIENT-CONTRACT.md](docs/CLIENT-CONTRACT.md)
- Default encryption is **off**; Comms cannot read Element E2EE DMs
