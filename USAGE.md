# Structs Matrix Chat — Guild Administration Guide

> **Homeserver packaging** for Synapse + MAS lives in this repo ([README.md](./README.md), [docs/SETUP.md](./docs/SETUP.md)).  
> Matrix user IDs look like `@1-42:matrix.guild.example` where `1-42` is `player.id` (OIDC `sub`), not a wallet address.

## Table of Contents

- [Initial Setup & Bootstrapping](#initial-setup--bootstrapping)
- [Admin Accounts](#admin-accounts)
- [Managing Rooms (Channels)](#managing-rooms-channels)
- [Spaces (Guild Organization)](#spaces-guild-organization)
- [Moderation](#moderation)
- [Federation Management](#federation-management)
- [Automated Setup via the Webapp](#automated-setup-via-the-webapp)
- [Admin API Reference](#admin-api-reference)
- [Day-to-Day Operations](#day-to-day-operations)

---

## Initial Setup & Bootstrapping

When a guild first deploys the Matrix stack (Synapse + MAS), there are no users and no rooms. The bootstrapping process creates the first admin account and sets up the guild's default rooms.

Authentication is delegated to **Matrix Authentication Service (MAS)**, which uses the guild webapp as its upstream OIDC identity provider. Users are created automatically in MAS the first time they complete the webapp's Cosmos signature login. Admin privileges, however, are managed in MAS.

### The Bootstrap Problem

Every player can log in via Cosmos signature, but MAS needs to know which users are **administrators**. Admin is an account-level privilege (separate from room power levels) that lets a user request the `urn:synapse:admin:*` token scope, which grants access to the Synapse Admin API, as well as the MAS Admin API.

### First Login Flow

1. Guild operator starts the Matrix stack (`docker compose up structs-matrix structs-mas`)
2. Guild operator logs in through the webapp (or any Matrix client) using their Cosmos signature — MAS auto-provisions their account from the webapp's OIDC claims (`sub` = Cosmos address)
3. Guild operator grants themselves admin via the MAS CLI (see below) — a one-time host-level action
4. They now have full access to the MAS and Synapse Admin APIs and can manage the homeserver

### Granting Admin via the MAS CLI

The `mas-cli` tool inside the MAS container manages account flags:

```bash
# Promote an existing user (after their first Cosmos / OIDC login) to admin
# localpart is player.id, e.g. 1-42
docker compose exec mas mas-cli manage set-admin \
  1-42

# Or register a user ahead of time with admin rights
docker compose exec mas mas-cli manage register-user \
  --admin \
  1-42
```

When that user logs in via the webapp's Cosmos → OIDC flow, MAS links the upstream identity by localpart (`sub` = player id), and their sessions can carry admin scope.

### Issuing an Admin Access Token

For scripts and the Synapse Admin API, issue a compatibility token for the admin account:

```bash
docker compose exec mas mas-cli manage issue-compatibility-token \
  --yes-i-want-to-grant-synapse-admin-privileges \
  1-42
```

The returned token works as `$ADMIN_ACCESS_TOKEN` in all the API examples below.

---

## Admin Accounts

### Server Admin vs Room Admin

These are two separate concepts in Matrix:

| Privilege         | Scope                | How it's granted                          |
|-------------------|----------------------|-------------------------------------------|
| **Server admin**  | Entire homeserver    | Admin flag on the MAS account (`can_request_admin`) |
| **Room admin**    | Single room          | Power level 100 (or whatever is configured) in that room. Note: the room *creator* holds infinite power in room v12 |

A server admin can:
- Access the MAS Admin API (account management)
- Access the Synapse Admin API (room, federation, media management)
- Query and manage any room on the homeserver
- Deactivate accounts
- Block/allow federation with other servers
- View server statistics and health

A room admin can:
- Ban/kick/mute users in that specific room
- Change room settings (name, topic, join rules, power levels)
- Promote/demote other users within that room
- Set server ACLs for that room

A server admin is **not** automatically a room admin in every room. They can, however, use the Admin API to make themselves a room member or grant themselves power in any room on their server (in v12 rooms, this works by puppeting the room creator).

### Which Admin API Does What (Under MAS)

With authentication delegated to MAS, **account management moves from Synapse to MAS**. The following Synapse Admin API endpoints are disabled and have MAS equivalents:

| Task | Old Synapse endpoint (disabled under MAS) | Now done via |
|---|---|---|
| Grant/revoke server admin | `PUT /_synapse/admin/v2/users/{id}` with `admin` | `mas-cli manage set-admin` / MAS Admin API `can_request_admin` |
| Reset password | `/_synapse/admin/v1/reset_password` | Not applicable — no passwords; Cosmos signature only |
| Registration tokens | `/_synapse/admin/v1/registration_tokens` | Not applicable — accounts provisioned via webapp OIDC |
| Log in as user (puppeting) | `/_synapse/admin/v1/users/{id}/login` | `mas-cli manage issue-compatibility-token` |
| Deactivate account | `/_synapse/admin/v1/deactivate/{id}` | MAS Admin API `POST /api/admin/v1/users/{id}/deactivate` |

Room management, federation management, media, and moderation endpoints remain on the Synapse Admin API and work as documented below.

### Promoting Additional Admins

```bash
# Via the MAS CLI (inside the MAS container)
docker compose exec structs-mas mas-cli manage set-admin \
  structs1xyz...new_admin_address
```

Or via the MAS Admin API (requires an admin token):

```bash
curl -X PUT "https://auth.guild.structs.game/api/admin/v1/users/{mas_user_id}" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"can_request_admin": true}'
```

### Demoting Admins

```bash
docker compose exec structs-mas mas-cli manage set-admin --no-admin \
  structs1xyz...former_admin_address
```

Note: this stops *new* sessions from carrying admin scope. Revoke the user's existing sessions (via the MAS Admin API or `mas-cli`) to cut off tokens that were already issued.

### Listing All Users

User listing is available from either API; the Synapse view remains useful for room/device counts:

```bash
# Synapse view (still available under MAS)
curl "https://matrix.guild.structs.game/_synapse/admin/v2/users?from=0&limit=100" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"

# MAS view (account status, upstream identity links)
curl "https://auth.guild.structs.game/api/admin/v1/users" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

---

## Managing Rooms (Channels)

### Room Version 12: Who Should Create Rooms

Room version 12 (the default for new rooms) grants the **room creator infinite power level, permanently**. The creator does not appear in the power levels `users` map; their privilege is inferred from the `m.room.create` event and can never be removed. Two operational rules follow:

1. **Create all guild rooms from a long-lived guild bot account**, not a personal player account. Guild leadership can change; a room's creator cannot. Human leaders get power level 100 in each room instead.
2. **For co-ownership, set `additional_creators` at creation time** (also immutable) — for example, one trusted account per founding guild in a cross-guild room:

```javascript
const room = await matrixClient.createRoom({
    name: "Alpha-Beta Diplomacy",
    creation_content: {
        additional_creators: [
            "@guild-bot:beta.structs.game",
        ]
    },
    // ...
});
```

Also note: upgrading a room (sending `m.room.tombstone`) requires power level 150 by default in v12, so ordinary admins at 100 cannot upgrade a room and assume creator rights.

### Creating a Room

**From the webapp (programmatic, using matrix-js-sdk):**

```javascript
const room = await matrixClient.createRoom({
    name: "General",
    topic: "General guild discussion",
    room_alias_name: "general",     // becomes #general:guild.structs.game
    visibility: "private",          // "public" to list in directory
    preset: "private_chat",         // or "public_chat", "trusted_private_chat"
    initial_state: [
        {
            type: "m.room.join_rules",
            content: { join_rule: "public" }  // or "invite", "knock", "restricted"
        }
    ],
    power_level_content_override: {
        users_default: 0,
        events_default: 0,          // everyone can send messages
        ban: 50,
        kick: 50,
        redact: 50,
        state_default: 50,
        events: {
            "m.room.name": 100,
            "m.room.power_levels": 100,
            "m.room.history_visibility": 100,
            "m.room.server_acl": 100,
        },
        users: {
            // In room v12, the creator is NOT listed here — they hold
            // infinite power implicitly. List human admins explicitly:
            // "@structs1leader...:guild.structs.game": 100,
        }
    }
});
```

**From the Admin API (server admin):**

```bash
curl -X POST "https://matrix.guild.structs.game/_synapse/admin/v1/rooms" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "General",
    "topic": "General guild discussion",
    "room_alias_name": "general",
    "preset": "public_chat"
  }'
```

**From any Matrix client (Element, FluffyChat, etc.):**
Use the "Create Room" UI. Set name, topic, and permissions through the client interface.

### Room Presets

| Preset                  | Join Rule | History Visibility | Guest Access | Power Defaults   |
|------------------------|-----------|--------------------|--------------|------------------|
| `private_chat`         | invite    | shared             | forbidden    | All members = 0  |
| `trusted_private_chat` | invite    | shared             | forbidden    | All members = 100|
| `public_chat`          | public    | shared             | forbidden    | Members = 0      |

In all presets under room v12, the creating account holds infinite power implicitly (it is not listed in the power levels map).

### Creating Common Room Types

**Announcement Channel (read-only for most):**

```javascript
const room = await matrixClient.createRoom({
    name: "Announcements",
    room_alias_name: "announcements",
    preset: "public_chat",
    power_level_content_override: {
        users_default: 0,
        events_default: 50,     // Only level 50+ can post
        users: {
            [`@${leaderAddress}:${serverName}`]: 100,
            [`@${officerAddress}:${serverName}`]: 50,
        }
    }
});
```

**Moderated Discussion (new users are view-only until promoted):**

```javascript
const room = await matrixClient.createRoom({
    name: "Trade",
    room_alias_name: "trade",
    preset: "public_chat",
    power_level_content_override: {
        users_default: 0,
        events_default: 10,     // Need level 10+ to post
        events: {
            "m.reaction": 0,    // But anyone can react
        }
    }
});
```

**Private Officers Room:**

```javascript
const room = await matrixClient.createRoom({
    name: "Officers",
    room_alias_name: "officers",
    preset: "private_chat",
    invite: [
        `@${officer1}:${serverName}`,
        `@${officer2}:${serverName}`,
    ],
    initial_state: [
        {
            type: "m.room.join_rules",
            content: { join_rule: "invite" }
        }
    ]
});
```

### Listing Rooms

**Admin API (all rooms on the server):**

```bash
curl "https://matrix.guild.structs.game/_synapse/admin/v1/rooms?limit=100" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

**Client-side (rooms the user is in):**

```javascript
const rooms = matrixClient.getRooms();
rooms.forEach(room => {
    console.log(room.name, room.roomId, room.getJoinedMemberCount());
});
```

### Deleting / Shutting Down a Room

```bash
# Kick all members and block the room from being rejoined
curl -X DELETE "https://matrix.guild.structs.game/_synapse/admin/v2/rooms/$ROOM_ID" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "This room has been closed by guild administration.",
    "block": true,
    "purge": true
  }'
```

- `block: true` prevents the room from being recreated with the same alias
- `purge: true` deletes all messages from the database (recovers disk space)

---

## Spaces (Guild Organization)

A Space is a room that acts as a container for other rooms, providing hierarchical organization. A guild's Space is the top-level entry point for all of its chat.

### Creating a Guild Space

```javascript
const space = await matrixClient.createRoom({
    name: "Guild Alpha",
    topic: "Official Space for Guild Alpha",
    room_alias_name: "guild-alpha",
    creation_content: {
        type: "m.space"       // This makes it a Space, not a regular room
    },
    initial_state: [
        {
            type: "m.room.join_rules",
            content: { join_rule: "public" }
        }
    ],
    power_level_content_override: {
        users_default: 0,
        events_default: 100,  // Only admins can post in the Space itself
    }
});
```

### Adding Rooms to the Space

After creating rooms, link them to the guild Space:

```javascript
// Add #general to the guild Space
await matrixClient.sendStateEvent(spaceRoomId, "m.space.child", {
    via: ["guild-alpha.structs.game"],
    suggested: true           // Show this room prominently in the Space
}, generalRoomId);            // The state key is the child room's ID

// Add #announcements
await matrixClient.sendStateEvent(spaceRoomId, "m.space.child", {
    via: ["guild-alpha.structs.game"],
    suggested: true
}, announcementsRoomId);

// Add #officers (private, not suggested)
await matrixClient.sendStateEvent(spaceRoomId, "m.space.child", {
    via: ["guild-alpha.structs.game"],
    suggested: false          // Don't suggest to all members
}, officersRoomId);
```

### Space-Restricted Rooms

Rooms can be set so that only members of the guild Space can join:

```javascript
await matrixClient.sendStateEvent(roomId, "m.room.join_rules", {
    join_rule: "restricted",
    allow: [
        {
            type: "m.room_membership",
            room_id: spaceRoomId    // Must be a member of this Space
        }
    ]
});
```

This means: anyone who joins the guild Space can join this room, but outsiders cannot. No manual invites needed for guild members.

### Recommended Guild Space Structure

```
Guild Alpha (Space)
├── #announcements     (broadcast, officers post)
├── #general           (public, all members chat)
├── #trade             (moderated, verified traders)
├── #strategy          (public, all members)
├── #officers          (invite-only, leadership)
├── #diplomacy         (invite-only, cross-guild)
└── #bot-commands      (public, for game bot interactions)
```

---

## Moderation

### Kicking a User (Temporary Removal)

The user can rejoin unless the room is invite-only.

```javascript
await matrixClient.kick(roomId, userId, "Reason for kick");
```

**Admin API (server admin can kick from any room on their server):**

```bash
curl -X POST "https://matrix.guild.structs.game/_synapse/admin/v1/rooms/$ROOM_ID/kick" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "@offending_user:some.server",
    "reason": "Disruptive behavior"
  }'
```

### Banning a User (Permanent Removal)

The user cannot rejoin until unbanned. Works across federation — you can ban a user from any server.

```javascript
await matrixClient.ban(roomId, userId, "Reason for ban");
```

```bash
# Admin API
curl -X POST "https://matrix.guild.structs.game/_synapse/admin/v1/rooms/$ROOM_ID/ban" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "@spammer:rogue-guild.example.com",
    "reason": "Spam"
  }'
```

### Unbanning a User

```javascript
await matrixClient.unban(roomId, userId);
```

### Muting a User (Lowering Power Level)

Drop the user's power level below `events_default` so they can read but not send:

```javascript
// Get current power levels
const powerEvent = room.currentState.getStateEvents("m.room.power_levels", "");
const powerLevels = powerEvent.getContent();

// Set user to level -1 (below any event threshold)
powerLevels.users = powerLevels.users || {};
powerLevels.users[userId] = -1;

await matrixClient.sendStateEvent(roomId, "m.room.power_levels", powerLevels);
```

### Unmuting a User

```javascript
const powerLevels = /* get current levels as above */;

// Remove the override (user falls back to users_default)
delete powerLevels.users[userId];
// Or set to a specific level:
// powerLevels.users[userId] = 10;

await matrixClient.sendStateEvent(roomId, "m.room.power_levels", powerLevels);
```

### Redacting (Deleting) a Message

Remove a specific message. The event is tombstoned, not fully deleted (other servers may still have it cached).

```javascript
await matrixClient.redactEvent(roomId, eventId, undefined, { reason: "Inappropriate content" });
```

### Promoting a User to Moderator

```javascript
const powerLevels = /* get current levels */;
powerLevels.users[userId] = 50;
await matrixClient.sendStateEvent(roomId, "m.room.power_levels", powerLevels);
```

### Promoting a User to Room Admin

```javascript
const powerLevels = /* get current levels */;
powerLevels.users[userId] = 100;
await matrixClient.sendStateEvent(roomId, "m.room.power_levels", powerLevels);
```

### Banning an Entire Server from a Room

If a rogue guild's server is flooding a room with bots or spam:

```javascript
await matrixClient.sendStateEvent(roomId, "m.room.server_acl", {
    allow: ["*"],
    deny: ["rogue-guild.example.com"],
    allow_ip_literals: false
});
```

All users from that server are immediately removed from the room and cannot rejoin.

### Deactivating a User Account (Server Admin)

Permanently deactivate a user on your own homeserver. This logs them out of all sessions and prevents future login. Since accounts are managed by MAS, deactivation goes through the MAS Admin API (Synapse's deactivate endpoint is disabled under delegated auth):

```bash
curl -X POST "https://auth.guild.structs.game/api/admin/v1/users/{mas_user_id}/deactivate" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

MAS propagates the deactivation to Synapse. Note that deactivation alone does not stop the player from re-authenticating via the webapp if their guild membership is still active — pair it with the guild-level ban in your game systems.

### Shadow Banning (Server Admin)

The user can still post but their messages are only visible to themselves. Useful for dealing with trolls without alerting them.

```bash
curl -X POST "https://matrix.guild.structs.game/_synapse/admin/v1/users/@troll:guild.structs.game/shadow_ban" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

---

## Federation Management

### Checking Federation Status

Verify your server can federate with another:

```bash
# Check if your server can reach another server
curl "https://matrix.guild.structs.game/_matrix/federation/v1/version"

# Synapse Admin API: federation destinations
curl "https://matrix.guild.structs.game/_synapse/admin/v1/federation/destinations" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

### Blocking a Server (Homeserver-Wide)

Prevent all federation with a specific server. No rooms, no user lookups, nothing.

```bash
# Block a server
curl -X PUT "https://matrix.guild.structs.game/_synapse/admin/v1/federation/destinations/rogue-guild.example.com" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"blocked": true}'
```

### Unblocking a Server

```bash
curl -X PUT "https://matrix.guild.structs.game/_synapse/admin/v1/federation/destinations/rogue-guild.example.com" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"blocked": false}'
```

### Viewing Federation Connections

```bash
# List all servers your homeserver has communicated with
curl "https://matrix.guild.structs.game/_synapse/admin/v1/federation/destinations?limit=100" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN"
```

Returns each destination server with:
- Last successful/failed federation attempt timestamps
- Retry counts and timing
- Whether the destination is blocked

### Disabling Federation Entirely

In `homeserver.yaml`, to run a fully isolated guild chat:

```yaml
global:
  disable_federation: true
```

This prevents any communication with other Matrix servers. The guild's chat is completely self-contained.

---

## Automated Setup via the Webapp

Since guild operators run the chat infrastructure alongside the webapp, the webapp backend can automate initial setup. This avoids requiring guild leaders to manually create rooms.

### Bootstrap Script Concept

When the Matrix stack starts for the first time, a bootstrap script (or a startup task in the webapp) can:

1. Wait for Synapse and MAS to be healthy
2. Create the **guild bot account** in MAS and issue it an access token — the bot creates all rooms, so it (not a player) holds the permanent room v12 creator privilege
3. Create the guild Space
4. Create default rooms and add them to the Space
5. Set appropriate power levels and join rules (guild leaders get 100)

```bash
# Step 1: Create the guild bot account and issue its token (one-time)
docker compose exec structs-mas mas-cli manage register-user guild-bot
docker compose exec structs-mas mas-cli manage issue-compatibility-token guild-bot
# -> save the returned token as GUILD_BOT_TOKEN
```

```python
# Example bootstrap script (Python, runs once on first deploy)
import os
import requests

MATRIX_URL = "http://structs-matrix:8008"

# Authenticate as the guild bot using the token issued via mas-cli
headers = {
    "Authorization": f"Bearer {os.environ['GUILD_BOT_TOKEN']}",
    "Content-Type": "application/json",
}

# Create guild Space (the bot becomes its immutable creator)
space = requests.post(f"{MATRIX_URL}/_matrix/client/v3/createRoom", headers=headers, json={
    "name": f"Guild {GUILD_TAG}",
    "room_alias_name": f"guild-{GUILD_TAG.lower()}",
    "creation_content": {"type": "m.space"},
    "initial_state": [
        {"type": "m.room.join_rules", "content": {"join_rule": "public"}}
    ],
}).json()

space_id = space["room_id"]

# Create default rooms (guild leaders should be granted PL 100 in each)
default_rooms = [
    {"name": "General", "alias": "general", "events_default": 0},
    {"name": "Announcements", "alias": "announcements", "events_default": 50},
    {"name": "Trade", "alias": "trade", "events_default": 0},
    {"name": "Officers", "alias": "officers", "join_rule": "invite", "events_default": 0},
]

for room_def in default_rooms:
    room = requests.post(f"{MATRIX_URL}/_matrix/client/v3/createRoom", headers=headers, json={
        "name": room_def["name"],
        "room_alias_name": room_def["alias"],
        "preset": "public_chat" if room_def.get("join_rule") != "invite" else "private_chat",
        "power_level_content_override": {
            "events_default": room_def["events_default"],
        }
    }).json()

    # Add room to guild Space
    requests.put(
        f"{MATRIX_URL}/_matrix/client/v3/rooms/{space_id}/state/m.space.child/{room['room_id']}",
        headers=headers,
        json={"via": [SERVER_NAME], "suggested": True}
    )
```

### Auto-Join for New Guild Members

Configure Synapse to automatically join new users into the guild's default rooms:

```yaml
# In homeserver.yaml
auto_join_rooms:
  - "#general:guild.structs.game"
  - "#announcements:guild.structs.game"

auto_join_rooms_for_guests: false
autocreate_auto_join_rooms: false       # We create them ourselves
auto_join_mxid_localpart: "guild-bot"   # The user that sends join invites
```

This way, when a new guild member authenticates for the first time and their account is auto-created, they're immediately placed in the guild's core rooms.

### Fleet public rooms (hybrid ensure)

Each player fleet gets a **public** room created by `@guild-bot` (never by the player):

| Field | Convention |
|---|---|
| Alias | `#fleet-{fleetId}` e.g. `#fleet-9-42:matrix.example` |
| Fleet id | `9-{playerIndex}` — Matrix user is `@1-{playerIndex}:…` |
| Owner PL | player MXID at power level 100 |

Idempotent script (token in `config/secrets/guild-bot.compatibility-token` or `GUILD_BOT_TOKEN`):

```bash
export MATRIX_SERVER_NAME=matrix.example
./scripts/ensure-fleet-room.py --player-id 1-42
# or: ./scripts/ensure-fleet-room.py --fleet-id 9-42
```

Full upgrade path (directory listing + MSC4108 QR + fleet): [docs/UPGRADE.md](docs/UPGRADE.md).

### Channel listing and QR device linking

- Public rooms (`visibility: "public"`) appear in Element Explore when Synapse has `enable_room_list_search: true` (default in this repo’s template).
- Primary second-device path is Element MSC4108 device linking (Synapse `msc4108_enabled` + MAS `/device`/`/link`). Fallback: deep-link OIDC / wallet login on the new device.

---

## Admin API Reference

Synapse admin endpoints are under `/_synapse/admin/` on the homeserver; MAS admin endpoints are under `/api/admin/v1/` on the auth service. Both require an admin access token.

### User Management

Account lifecycle is handled by MAS; Synapse retains read/moderation endpoints.

| Action                | Method | Endpoint                                           |
|-----------------------|--------|----------------------------------------------------|
| List users (Synapse view) | GET | `/_synapse/admin/v2/users?from=0&limit=100`        |
| Get user details      | GET    | `/_synapse/admin/v2/users/{user_id}`                |
| List users (MAS view) | GET    | `/api/admin/v1/users` (on MAS)                      |
| Grant/revoke admin    | PUT    | `/api/admin/v1/users/{id}` with `can_request_admin` (on MAS) |
| Deactivate user       | POST   | `/api/admin/v1/users/{id}/deactivate` (on MAS)      |
| Shadow ban            | POST   | `/_synapse/admin/v1/users/{user_id}/shadow_ban`     |
| List user's rooms     | GET    | `/_synapse/admin/v1/users/{user_id}/joined_rooms`   |
| Force join user       | POST   | `/_synapse/admin/v1/join/{room_id}`                 |
| Reset rate limits     | DELETE | `/_synapse/admin/v1/users/{user_id}/override_ratelimit` |

### Room Management

| Action                | Method | Endpoint                                           |
|-----------------------|--------|----------------------------------------------------|
| List rooms            | GET    | `/_synapse/admin/v1/rooms`                          |
| Get room details      | GET    | `/_synapse/admin/v1/rooms/{room_id}`                |
| Get room members      | GET    | `/_synapse/admin/v1/rooms/{room_id}/members`        |
| Get room state        | GET    | `/_synapse/admin/v1/rooms/{room_id}/state`          |
| Delete/shut down room | DELETE | `/_synapse/admin/v2/rooms/{room_id}`                |
| Block a room          | PUT    | `/_synapse/admin/v1/rooms/{room_id}/block`          |
| Make user room admin  | POST   | `/_synapse/admin/v1/rooms/{room_id}/make_room_admin`|

### Federation Management

| Action                   | Method | Endpoint                                              |
|--------------------------|--------|-------------------------------------------------------|
| List destinations        | GET    | `/_synapse/admin/v1/federation/destinations`           |
| Get destination details  | GET    | `/_synapse/admin/v1/federation/destinations/{server}`  |
| Block/unblock server     | PUT    | `/_synapse/admin/v1/federation/destinations/{server}`  |

### Server Management

| Action                | Method | Endpoint                                           |
|-----------------------|--------|----------------------------------------------------|
| Server version        | GET    | `/_synapse/admin/v1/server_version`                 |
| Purge room history    | POST   | `/_synapse/admin/v1/purge_history/{room_id}`        |
| Background updates    | GET    | `/_synapse/admin/v1/background_updates/status`      |

Full documentation:
- Synapse Admin API: https://element-hq.github.io/synapse/latest/usage/administration/admin_api/index.html
- MAS Admin API and `mas-cli`: https://element-hq.github.io/matrix-authentication-service/

---

## Day-to-Day Operations

### Monitoring

Synapse exposes Prometheus metrics when enabled in config:

```yaml
# homeserver.yaml
metrics:
  enabled: true
```

Key metrics to watch:
- `synapse_federation_send_queue_length` — federation backlog
- `synapse_storage_events_persisted_events_total` — event write rate
- `synapse_http_server_request_count` — API request volume
- `process_resident_memory_bytes` — RAM usage

### Database Maintenance

Synapse stores all room history. Over time, the database grows. To manage this:

**Message retention policy (per room):**

```javascript
await matrixClient.sendStateEvent(roomId, "m.room.retention", {
    max_lifetime: 2592000000,   // 30 days in milliseconds
    min_lifetime: 86400000,     // 1 day in milliseconds
});
```

**Purge old history (Admin API):**

```bash
curl -X POST "https://matrix.guild.structs.game/_synapse/admin/v1/purge_history/$ROOM_ID" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "purge_up_to_ts": 1672531200000
  }'
```

**Enable retention purge job in Synapse config:**

```yaml
retention:
  enabled: true
  default_policy:
    min_lifetime: 1d
    max_lifetime: 365d
  purge_jobs:
    - longest_max_lifetime: 365d
      interval: 1d
```

### Backups

Back up the following:
- **PostgreSQL databases** — `structs_matrix` (room state and history) and `structs_mas` (accounts, sessions, upstream identity links)
- **Signing key** — `matrix_key.pem` (if lost, the server loses its federation identity)
- **MAS secrets** — the MAS config's signing keys and the shared secret with Synapse
- **Media store** — uploaded files and avatars (in the `matrix-data` volume at `/data/media_store`)

```bash
# Database backups
docker compose exec structs-pg pg_dump -U structs_matrix structs_matrix > matrix_backup.sql
docker compose exec structs-pg pg_dump -U structs_mas structs_mas > mas_backup.sql

# Signing key backup
docker compose cp structs-matrix:/data/matrix_key.pem ./backup/matrix_key.pem
```

### Log Inspection

```bash
# Follow Synapse logs
docker compose logs -f structs-matrix

# Check for federation errors
docker compose logs structs-matrix 2>&1 | grep -i "federation"
```

### Restarting Without Downtime

Synapse handles restarts gracefully. Active connections will reconnect automatically (clients retry).

```bash
docker compose restart structs-matrix
```

Federation partners will retry failed deliveries with exponential backoff, so short maintenance windows cause no message loss.
