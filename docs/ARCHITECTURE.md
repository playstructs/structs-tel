# Architecture

## Components

```text
Element / Matrix client
        │
        ├─ HTTPS ─► Synapse (structs-matrix) ──► Postgres DB `synapse` on structs-pg
        │                │
        │                └─ shared secret ─► MAS (structs-mas) ──► Postgres DB `mas`
        │                                          │
        └─ OIDC login UI ──────────────────────────┘
                                                   │
                                                   ▼
                                         structs-webapp (OIDC IdP)
                                         issuer = https://<guild-webapp>
```

- **Wallet auth** stays in the webapp (Cosmos signature → PHP session).
- **MAS** is the Matrix auth service; it uses the webapp as upstream OIDC.
- **Synapse** trusts MAS for all logins (`matrix_authentication_service`).
- **Postgres** is the guild `structs-pg` container; Matrix uses separate databases.

## Identity

| Claim / field | Value |
|---|---|
| OIDC `sub` | `structs.player.id` (e.g. `1-42`) |
| Matrix user ID | `@1-42:<MATRIX_SERVER_NAME>` |
| `preferred_username` | player username (display only) |
| `primary_address` | Cosmos address (descriptive only; not localpart) |

Player IDs are immutable; wallet addresses are not — that is why `sub` is not the address.

## Trust boundaries

- MAS never sees Cosmos private keys or signatures.
- Client secret is shared only between webapp (hashed in `oidc_client`) and MAS config.
- Signing keys for Synapse federation and webapp OIDC JWTs are separate secrets.
- This compose joins the guild Docker network to reach `structs-pg` and (optionally) `structs-webapp` by hostname; public OIDC still uses the webapp’s HTTPS issuer URL.

## Room version

Default Synapse room version is **12** (creator infinite power). Bootstrap rooms with a long-lived bot account when you get to day-2 ops — see USAGE.md.
