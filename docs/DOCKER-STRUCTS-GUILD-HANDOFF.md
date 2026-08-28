# Handoff: docker-structs-guild team

**This document is a request / specification.** The `structs-tel` maintainers will **not** open PRs or edit `docker-structs-guild` directly. Please pull what you need from this repo.

## Goal

Allow guilds that want Matrix chat to run Synapse + MAS **alongside** the existing guild stack, sharing:

- Docker network (so services can resolve `structs-pg`, optionally `structs-webapp`)
- Postgres **host** (`structs-pg`) with **separate** databases `synapse` and `mas` (created by `structs-tel` init, not Sqitch)

Webapp OIDC remains owned by `structs-webapp` + OIDC Sqitch tables in the `structs` database.

## What already exists in structs-tel

| Artifact | Purpose |
|---|---|
| `compose.yaml` | `synapse` + `mas` (+ `matrix-db-init` profile) |
| `.env.example` | Required variables |
| `config/synapse/*.template` | Homeserver with MAS delegation, room v12 |
| `config/mas/*.template` | Upstream OIDC → webapp issuer |
| `scripts/init-matrix-dbs.sh` | `CREATE ROLE/DATABASE` on structs-pg |
| `docs/SETUP.md` | Operator procedure |

Suggested integration style (same idea as `compose-discord.yaml`):

```bash
docker compose -f compose.yaml -f compose-matrix.yaml up -d
```

where `compose-matrix.yaml` is either a copy of `structs-tel/compose.yaml` or a thin wrapper that sets project/network conventions.

## Asks for docker-structs-guild

1. **Document** (README) how to attach an optional Matrix compose on `GUILD_DOCKER_NETWORK` / default project network.
2. **Do not** put Synapse schema into Sqitch. Empty DB creation can stay in `structs-tel` init **or** you may optionally pre-create roles in the Postgres image — either is fine if documented.
3. **Proxy / Caddy** (wherever TLS lives today on crew: Caddy in front of nginx):
   - Host for Synapse client API (e.g. `matrix.<guild>`)
   - Host for MAS (e.g. `auth.<guild>`)
   - `/.well-known/matrix/client` including auth issuer → MAS public base
   - `/.well-known/matrix/server` for federation
   - Federation port **8448** published when federating
4. **Env passthrough** (optional): surface `OIDC_*` for the webapp service from guild `.env` so operators are not editing bind-mounted source only.
5. Keep Matrix **optional** — guilds without chat should not pull Synapse/MAS images.
6. **Postgres TLS for MAS:** `structs-pg` server certificates must be **X.509 v3**. MAS (rustls) rejects v1 certs with `UnsupportedCertVersion`. Prefer fixing cert generation in the Postgres image; operators can reissue from the existing key as a one-off (see `docs/CREW-REFERENCE.md`).

## Sample well-known (client)

```json
{
  "m.homeserver": {
    "base_url": "https://matrix.EXAMPLE"
  },
  "org.matrix.msc2965.authentication": {
    "issuer": "https://auth.EXAMPLE/",
    "account": "https://auth.EXAMPLE/account"
  }
}
```

## Sample well-known (server)

```json
{
  "m.server": "matrix.EXAMPLE:443"
}
```

## Ports (defaults from structs-tel)

| Port | Service | Notes |
|---|---|---|
| 8008 | Synapse client/federation (container) | Often bound to `127.0.0.1` behind Caddy |
| 8448 | Synapse federation | May bind public |
| 8081 | MAS | Often bound to `127.0.0.1` behind Caddy |

## Acceptance for “integrated”

- Operator can enable Matrix without forking Synapse.
- `structs-pg` remains single Postgres host.
- Webapp OIDC discovery works; Element login yields `@<player.id>:<server_name>`.
- Guilds that skip Matrix are unchanged.
