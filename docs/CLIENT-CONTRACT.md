# Client and guild contract (Comms, Element, every homeserver)

From native Matrix in Structs.app (Comms) plus Element. Protect the two
identity rules; implement the rest on **every** guild homeserver.

## Do not trade these away

| Rule | Why |
|---|---|
| Chat credential = play credential | Webapp OIDC → MAS → Synapse. No chat password, no second identity. |
| Matrix localpart = `player.id` | `@1-194:matrix.example` is player `1-194`. Addressable with no lookup. |

## What every guild homeserver must run

Templates in this repo already encode this. Existing deploys: re-render and
recreate Synapse + MAS per [UPGRADE.md](UPGRADE.md).

| # | Setting | Template | Why |
|---|---|---|---|
| 1a | Publish rooms | `visibility: "public"` at create + `room_list_publication_rules` allow `@guild-bot` only | `join_rule: public` does **not** list a room. Browse stays empty. |
| 1b | Federated directory | `allow_public_rooms_over_federation: true` | Otherwise `GET /publicRooms?server=<other>` is `M_FORBIDDEN`. |
| 2 | Presence | `presence.enabled: true` (explicit) | Roster / “who is around”. Do not copy “disable presence to save CPU”. |
| 3 | Default encryption | `encryption_enabled_by_default_for_room_type: "off"` (quoted) | Comms has no E2EE. Encrypted DMs are unreadable there, asymmetrically. |
| 4 | Aliases + power | Documented below; rooms created by `@guild-bot` | v12 creator is infinite and permanent. Alias lives on the **owner** homeserver. |
| 5 | Display name | MAS `displayname.action: force` from `preferred_username` | Stops local spoofing. Remote federated users can still lie; clients should keep folding. |
| 6a | Message search | `enable_search: true` | `POST /search` `order_by: recent`. |
| 6b | Raid bursts | `rc_message: 1.0/s burst 30` | Default 0.2/s burst 10 will 429 a fight. |

Leave `allow_public_rooms_without_auth` **false** (directory still requires a Matrix login).

## Decision: encryption

**Guild-adjacent rooms and DMs are unencrypted by policy.**

Comms cannot implement Megolm + cross-signing + key backup in the game client
on a useful timeline. Element encrypts DMs **it** creates even when Synapse
default is off. So:

- `@guild-bot` must never send `m.room.encryption`.
- Comms should create (or reuse) **unencrypted** DMs for player-to-player game
  chat.
- Element users talking to Comms users must use an unencrypted room, or the
  Comms side will show “encrypted message — this app cannot read it” while
  Element looks fine.

Do not “fix” this by teaching Comms E2EE unless product explicitly takes that
on. Do not reject `m.room.encryption` server-wide — that would break people who
want private Element-only rooms.

## Alias convention (discovery until every room is published)

A client can only mint an alias on **its own** homeserver. Per-object rooms
live on the **owner guild’s** server. That is a property of Matrix, not a bug.

| Kind | Alias localpart | Example | Host |
|---|---|---|---|
| Fleet | `fleet-{fleetId}` | `#fleet-9-42:matrix.crew.oh.energy` | Owner player’s guild (`9-N` ↔ player `1-N`) |
| Planet | `planet-{planetId}` | `#planet-2-15361:matrix.crew.oh.energy` | Owner guild |
| Guild lobby / named channel | short slug | `#orbital-hydro:matrix.crew.oh.energy` | That guild |

Always create via `@guild-bot` with `visibility: "public"` and a canonical
alias. Scripts: `scripts/ensure-fleet-room.py`, `scripts/ensure-published-room.py`.

Guessing aliases is a fallback, not the design. After publication + federated
directory, Comms can `GET /publicRooms?server=` instead of probing.

## Power levels (hide controls that will never work)

Synapse `public_chat` defaults, plus our owner-at-100 convention:

| Capability | Default PL | Ordinary member (0) |
|---|---:|---|
| Send messages (`events_default`) | 0 | yes |
| Invite | 0 | yes |
| Redact others | 50 | **no** |
| Kick / ban | 50 | **no** |
| State (name, topic, join rules, **pins**) | 50 | **no** |
| Room owner (fleet/planet) | 100 | owner only |
| `@guild-bot` (v12 creator) | infinite | n/a |

Do not offer pin / redact / topic UI to PL 0. Surface “you do not have
permission” only when the user actually has a path to gain it.

## `m.mentions` (every client, including bots)

Send [MSC3952](https://github.com/matrix-org/matrix-spec-proposals/blob/main/proposals/3952-intentional-mentions.md)
`m.mentions` on messages that target a user or `@room`. Guessing from body
text is both over- and under-inclusive. This is **not** a Synapse flag.

## Display names

MAS forces `preferred_username` (webapp `player.username`, the name the chain
already settled) on every login. Local Element profile edits will not stick
after the next OIDC login.

Federation: a user on another homeserver can still set any display name.
Clients should keep stripping bidi/zero-width, folding confusables, and
appending the unforgeable MXID localpart on collision. Server-side force does
not protect against remote impersonation.

## What each team implements

**Guild ops (every structs-tel deploy)**

1. Pull this repo, `./scripts/render-configs.sh`, recreate `synapse` and `mas`.
2. Confirm `allow_public_rooms_over_federation: true`, `presence.enabled: true`,
   encryption `"off"`, `enable_search: true`.
3. Create/publish all guild and per-object rooms as `@guild-bot` with
   `visibility: "public"`. Backfill existing `join_rule: public` rooms:
   `PUT /_matrix/client/v3/directory/list/room/{roomId}` `{"visibility":"public"}`
   (must be guild-bot; publication rules deny everyone else).
4. Do not disable presence “to save CPU” on guild-sized homeservers.

**Comms / Structs.app**

1. Keep localpart = player id; keep OIDC wallet login.
2. Prefer directory + federated `publicRooms`; keep alias probe as fallback.
3. Create game DMs **without** encryption; never treat Element-encrypted DMs as
   readable.
4. Send `m.mentions`. Hide pin/redact/topic for PL 0.
5. Keep display-name folding for **remote** users.

**Element / other Matrix clients**

1. Expect unencrypted guild rooms.
2. If you encrypt a DM, the game client will not read it. Prefer an unencrypted
   DM or a published object room.

**structs-webapp**

1. Keep `sub` = `player.id`.
2. Keep `preferred_username` / `name` = `player.username` (on-chain name).
   Empty username falls back to `sub` in MAS.
3. Do not let players mint guild/fleet/planet rooms from the SPA (v12 creator).

## Verify

```bash
# Directory lists published rooms
curl -sS -X POST "http://127.0.0.1:8008/_matrix/client/v3/publicRooms" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"limit":50}' | jq '.chunk[] | {name,canonical_alias}'

# Federated directory (from another homeserver’s perspective)
# GET /_matrix/federation/v1/publicRooms?include_all_networks=false
# or client: GET /_matrix/client/v3/publicRooms?server=matrix.other.guild

grep -E 'allow_public_rooms_over_federation|encryption_enabled|enable_search|^presence:|rc_message' \
  config/synapse/homeserver.yaml
grep -n 'action: force' config/mas/config.yaml
```
