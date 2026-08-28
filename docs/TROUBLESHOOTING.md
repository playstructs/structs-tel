# TROUBLESHOOTING

## Webapp `/.well-known/openid-configuration` → 404

- `OIDC_ENABLED` is not `true` in the env the **running** container sees.
- Restart webapp after env change; confirm with `docker exec ... printenv OIDC_ENABLED`.

## Webapp `/oauth/jwks` → 500

- Private/public key missing at `OIDC_JWT_*_PATH` inside the container.
- Permissions / bind-mount path wrong.
- Run `php bin/console app:oidc:generate-key` and persist files.

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

- Port **8448** closed or not delegated.
- `.well-known/matrix/server` missing/wrong.
- TLS certificate problems on federation endpoint.

## Element cannot find auth issuer

- `.well-known/matrix/client` missing `org.matrix.msc2965.authentication` (or current auth discovery key your Element version expects).
- `issuer` must be the **MAS** public base, not the webapp (webapp is upstream of MAS).
