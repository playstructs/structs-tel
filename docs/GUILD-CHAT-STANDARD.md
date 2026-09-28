# Guild chat server standard

For every team running a Structs guild Matrix homeserver (Synapse + MAS on
structs-tel). The reference servers, **Orbital Hydro** (`matrix.crew.oh.energy`)
and **SN Corp** (`matrix.beta.playstructs.com`), run exactly this as of
2026-09-28. Following it keeps chat consistent between guilds: players see the
same rooms, the same names, and the same (plain) messages in Comms and in
Element, whichever guild hosts them.

If you run structs-tel, pull the latest templates and follow
[UPGRADE.md §9](UPGRADE.md#9-guild-chat-standard--e2ee-off-room-policy-display-name-lock-2026-09-28).
Everything below is already in the templates; this document explains what and why.

## Summary

| Area | Standard |
|---|---|
| Room directory | Every guild room is published to the directory by `@guild-bot`. Other guilds can browse it over federation. |
| Presence | On. |
| Encryption | Off. The server refuses it for its own users. |
| Room naming | Fixed alias scheme; only `@guild-bot` creates aliased or public rooms. |
| Display names | Set by the identity provider (the guild webapp), unforgeable, and not editable in chat. |

## 1. Room directory (Browse / Explore)

**Problem.** A room with `join_rule: public` is joinable but is *not* listed.
Listing is a separate flag (`visibility: public` at creation, or
`PUT /directory/list/room/{roomId}`). Synapse also denies all publication until
`room_list_publication_rules` is set. Result: Browse is empty.

**Standard.**

```yaml
enable_room_list_search: true
room_list_publication_rules:
  - user_id: "@guild-bot:<server_name>"
    action: allow
  - action: deny
allow_public_rooms_over_federation: true   # other guilds' Browse can list you
```

Create rooms with `scripts/ensure-published-room.py` or
`scripts/ensure-fleet-room.py`; both create as `@guild-bot`, set the alias, and
publish. Backfill an existing guild-bot room:

```bash
curl -X PUT "http://127.0.0.1:8008/_matrix/client/v3/directory/list/room/$ROOM" \
  -H "Authorization: Bearer $GUILD_BOT_TOKEN" -d '{"visibility":"public"}'
```

Leave `allow_public_rooms_without_auth` false; Browse needs a Matrix login.

## 2. Presence

**Problem.** Many “tune Synapse” guides disable presence to save CPU. That
removes online status, rosters, and “who is around” for everyone, on your
server and in rooms shared with other guilds.

**Standard.** Set it explicitly so a copied config cannot turn it off:

```yaml
presence:
  enabled: true
```

## 3. End-to-end encryption: off

**Problem.** Comms (the in-game client) has no E2EE. Element encrypts new DMs
by default. One encrypted room reads fine in Element and shows “unable to
decrypt” in Comms, so the conversation silently splits.

**Standard.** Three layers, all required:

1. Synapse never default-encrypts:
   ```yaml
   encryption_enabled_by_default_for_room_type: "off"   # quoted
   ```
2. Tell Element to hide encryption. In `/.well-known/matrix/client` (Synapse
   `extra_well_known_client_content`, **and** in your reverse proxy if it
   answers that URL itself, as the structs Caddy configs do):
   ```json
   "io.element.e2ee": {"default": false, "force_disable": true}
   ```
3. Refuse it server-side with `modules/structs_chat_policy.py`
   (Synapse module, mounted by `compose.yaml`). Local users get
   `403 This event is not allowed in this context` on any `m.room.encryption`,
   including in `createRoom`.

Limits, stated plainly:

- Rooms already encrypted stay encrypted. Matrix has no way to turn it off.
- Clients that ignore the well-known hint (some mobile clients, Element X
  among them) will get a 403 when they try to create an encrypted DM, rather
  than a room Comms can't read. Players should use Element Web/Desktop or Comms.
- Remote users are never blocked, so federation cannot diverge. A room owned by
  a guild that does not follow this standard can still be encrypted.

## 4. Room naming and who may create what

Room aliases live on the homeserver of the guild that **owns** the thing.
Room v12 gives the room creator permanent, unremovable top power, so the creator
must be the guild's bot, never a player.

| Room | Alias | Created by | Visibility |
|---|---|---|---|
| Guild lobby | `#<guild-slug>:<server>` e.g. `#orbital-hydro` | `@guild-bot` | public, published |
| Guild channels | `#<topic>` e.g. `#help`, `#infrastructure` | `@guild-bot` | public, published |
| Fleet | `#fleet-<fleetId>` e.g. `#fleet-9-42` (fleet `9-N` ↔ player `1-N`) | `@guild-bot`, owner at PL 100 | public, published |
| Planet | `#planet-<planetId>` e.g. `#planet-2-15361` | `@guild-bot`, owner at PL 100 | public, published |
| DMs and private groups | none | any player | invite / knock / restricted |

Rules: lowercase, hyphens, no guild prefix (the server name already says which
guild). One room per slug; don't create `#sn-corp` and `#sncorp`.

**Enforced by:**

```yaml
alias_creation_rules:            # Synapse default lets anyone mint any alias
  - user_id: "@guild-bot:<server_name>"
    alias: "*"
    room_id: "*"
    action: allow
  - action: deny
```

plus `structs_chat_policy` (`room_managers: ["@guild-bot:<server_name>"]`):
only room managers may set `join_rule: public`. Players can still create DMs and
private rooms.

**Client consequence.** A client that creates a fleet or planet room as the
player (Comms did, for `#planet-*`) now gets 403. The room must come from the
guild side: `ensure-published-room.py` / `ensure-fleet-room.py`, or a webapp
hook that calls them. Clients should resolve the alias, then join. They should
not fall back to creating the room.

## 5. Impersonation: fixed in the identity provider

**Problem.** On-chain usernames are not unique. On 2026-09-28 four names were shared
by 24 players (case-insensitive), including a second `abstrct` next to the
maintainer `Abstrct`. Chat used the username as-is, and users could also rename
themselves in Element between logins, or per room.

**Standard.** The guild webapp (OIDC identity provider) issues the display
name, and nothing downstream may change it:

| Claim | Value |
|---|---|
| `sub` | player id, e.g. `1-406` (becomes `@1-406:<server>`) |
| `preferred_username` | on-chain username, unchanged |
| `name` | username, or `username (player-id)` if any other player has the same name case-insensitively, or the name mixes Latin with another script |

The chain already rejects bidi overrides, zero-width and combining characters
in player names (`structsd` `ValidatePlayerName`).

MAS copies `name` onto the Matrix profile at every login:

```yaml
displayname:
  action: force
  template: "{{ user.name or user.preferred_username or user.sub }}"
```

Synapse refuses user-side changes (MAS writes as admin, so it still works):

```yaml
enable_set_displayname: false
allow_per_room_profiles: false
```

A new name takes effect at the player's next login. Remote users are named by
their own guild's identity provider, which is why every guild needs this.
Clients should still append the MXID localpart when two members share a name.

## Also in the template

| Setting | Why |
|---|---|
| `enable_search: true` | Message search |
| `rc_message: 1.0/s, burst 30` | Default 0.2/s burst 10 rate-limits raid chat |
| `retention.enabled` (no default policy) | Rooms that set `m.room.retention` get purged; others untouched |
| `experimental_features.msc4108_enabled` | Element QR sign-in |

## What the reference servers looked like, and what changed (2026-09-28)

| Finding | Orbital Hydro | SN Corp | Action |
|---|---|---|---|
| Public rooms missing from Browse | `#planet-2-22432`, `#planet-2-21411` (player-created, so un-publishable) | none | Recreated as guild-bot rooms (owner `@1-194` PL 100), aliases moved, members invited, old rooms left with a “moved” notice |
| Duplicate lobby | — | `#sn-corp` (11 members) and `#sncorp` (guild-bot, 3 members) | `#sncorp` now resolves to `#sn-corp`; old room unlisted and tombstoned |
| Presence | on | on | explicit in template (no change needed) |
| Encryption | 1 player DM encrypted; Element not told to stop | none | three-layer E2EE-off applied |
| Players could mint aliases / public rooms | yes | yes | `alias_creation_rules` + policy module |
| Players could rename in chat | yes (between logins, per room) | yes | display-name lock |
| Shared usernames | 4 names, 24 players (chain-wide) | same | webapp `name` claim disambiguates; MAS reads it |

Verified on SN Corp as a non-bot user: encrypted/public/aliased `createRoom` → 403,
private → 200, display-name change → 400, per-room override stripped, local and
federated `publicRooms` (crew, crab.la) list rooms, presence round-trips.

## Checklist

- [ ] `POST /publicRooms` lists your guild rooms; `publicRooms?server=<you>` works from another guild
- [ ] Every aliased room's creator is `@guild-bot`
- [ ] `presence.enabled: true`
- [ ] `/.well-known/matrix/client` has `io.element.e2ee.force_disable: true`
- [ ] Synapse log shows `Loaded module <structs_chat_policy.StructsChatPolicy`
- [ ] Non-bot user: encrypted `createRoom` → 403; `public_chat` → 403; alias → 403; private room → 200
- [ ] `GET /capabilities` → `m.set_displayname.enabled: false`
- [ ] MAS `displayname` template reads `user.name`; webapp emits disambiguated `name`

Questions: SN Corp infrastructure (`#infrastructure:matrix.beta.playstructs.com`).
