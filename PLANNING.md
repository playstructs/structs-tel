# Structs Decentralized Guild Chat — Planning Document

## Overview

Adding decentralized chat to the Structs game, where each guild can choose to offer chat infrastructure and manage moderation independently. Chat rooms can span multiple guild servers via federation, while accounts remain managed by each guild.

### Requirements

1. **Decentralized** — each guild runs its own chat server as part of their existing infrastructure
2. **Federated** — chat rooms can span multiple guild servers
3. **Custom authentication** — users authenticate using their Cosmos-based structs address via cryptographic message signing (same model as the existing webapp)
4. **Web-embeddable** — chat integrates directly into the Structs webapp, though users may also use third-party clients
5. **Guild-managed moderation** — each guild controls moderation for its own members and rooms
6. **Optional participation** — guilds can choose whether to offer chat or not
7. **Text-focused** — multimedia and voice are not current priorities but may be added later

---

## Protocol Decision: Matrix

### Why Matrix Over XMPP

| Requirement                  | Matrix                                      | XMPP                                      |
|------------------------------|---------------------------------------------|--------------------------------------------|
| Decentralized (guild=server) | Excellent (homeserver per guild)             | Excellent (server per guild)               |
| Federation (cross-guild)     | Excellent (first-class)                      | Good (MUC federation has quirks)           |
| Custom Cosmos auth           | Good (MAS + upstream OIDC provider)          | Good (external auth in Prosody/ejabberd)   |
| Web embedding                | **Excellent** (matrix-js-sdk + sliding sync) | Fair (Converse.js, Strophe.js)             |
| Moderation                   | Excellent (power levels, Mjolnir/Draupnir)  | Good (MUC roles)                           |
| Resource usage               | Moderate (Synapse ~300MB–1GB RAM)            | **Excellent** (Prosody ~30–50MB RAM)       |
| Future voice/video           | **Excellent** (MatrixRTC / Element Call)     | Fair (Jingle, less mature)                 |
| E2E encryption               | Excellent (Megolm)                           | Good (OMEMO, inconsistent across clients)  |
| 3rd party clients            | Good (Element X, FluffyChat, etc.)           | Good (Gajim, Conversations, etc.)          |
| Operational complexity       | Moderate                                     | **Low**                                    |

### Key Reasons for Matrix

1. **Web integration** — `matrix-js-sdk` (actively maintained) enables building a first-class chat experience directly in the game UI, rather than bolting on a separate app. Synapse's native support for **Simplified Sliding Sync** (MSC4186, part of Matrix 2.0) makes an embedded client sync near-instantly even in large rooms. Note: `matrix-react-sdk` no longer exists as a standalone SDK — it was absorbed into `element-web` in October 2024. For widget-style embedding, `matrix-widget-toolkit` is an alternative.
2. **Custom auth** — Matrix Authentication Service (MAS) supports upstream OIDC providers, letting the existing webapp (with its Cosmos signature validation) act as the identity provider for chat
3. **Guild-to-homeserver mapping** — each guild runs a Matrix homeserver; the guild's homeserver manages its members; this is native to how Matrix works
4. **Spaces** — Matrix Spaces are hierarchical room groupings that map naturally to guilds
5. **Federation** — cross-guild rooms are a first-class concept with robust state resolution
6. **Future-proofing** — Matrix 2.0 shipped native group VoIP (MatrixRTC / Element Call) if voice is ever needed

### Homeserver Choice: Synapse

**Synapse** (maintained by Element, AGPLv3-licensed since v1.99) is the chosen homeserver because it is the only implementation with stable MAS integration, which the custom auth architecture depends on. The AGPL license is not a concern for guilds running their own servers; it only matters for anyone distributing modified server builds.

The homeserver landscape has shifted:

- **Dendrite** (the original lightweight recommendation) is effectively dormant — archived at matrix.org in late 2024 and only minimally maintained under element-hq. Not recommended for new deployments.
- **Tuwunel** (Rust, official successor to conduwuit, developed by full-time staff and sponsored by the Swiss government) is the credible lightweight alternative — a single binary with RocksDB, no PostgreSQL needed, benchmarked outperforming multi-worker Synapse on sync under load. However, it does not support MAS or custom auth flows, so it cannot satisfy the Cosmos auth requirement today. A Synapse-to-Tuwunel migration path is planned upstream; small guilds may revisit this once auth support matures.

The tradeoff is resource usage — Synapse plus MAS uses more RAM than a Rust homeserver — but since guilds already run a full blockchain node, PostgreSQL, a webapp, NATS, and other services, this is a manageable addition.

### Security Baseline

The Matrix protocol had a coordinated security release in August 2025 (CVE-2025-49090 and a companion state-resolution vulnerability), which introduced **room version 12** and spec v1.16. Deployment requirements:

- Run Synapse at or above the August 2025 security release (v1.135.2+); in practice, always deploy the latest stable image
- Default new rooms to **room version 12** (`default_room_version: "12"` in `homeserver.yaml`)
- Room version 12 also changes creator semantics — see the Moderation Model section

### Other Options Considered

| Option                   | Notes                                                                                      |
|--------------------------|--------------------------------------------------------------------------------------------|
| **Nostr**                | Uses secp256k1 keys (same curve as Cosmos) but chat capabilities are immature              |
| **IRC (IRCv3)**          | Ultra-lightweight but lacks persistent history, auth, encryption, and multimedia            |
| **Rocket.Chat/Mattermost** | Self-hosted but not truly federated; each guild would be an island                       |
| **Custom via libp2p**    | Maximum control but requires building a chat protocol from scratch                         |

---

## Architecture

### Guild-to-Homeserver Mapping

```
Guild Alpha (alpha.structs.game)         Guild Beta (beta.structs.game)
┌─────────────────────────┐              ┌─────────────────────────┐
│  Synapse homeserver     │              │  Synapse homeserver     │
│                         │              │                         │
│  @player1:alpha...game  │◄────HTTPS───►│  @player3:beta...game   │
│  @player2:alpha...game  │  Federation  │  @player4:beta...game   │
│                         │              │                         │
│  Rooms:                 │              │  Rooms:                 │
│   #general (local only) │              │   #general (local only) │
│   #global-trade ────────┼──────────────┼── #global-trade         │
│   #alpha-beta-diplomacy ┼──────────────┼── #alpha-beta-diplomacy │
└─────────────────────────┘              └─────────────────────────┘
```

- Each guild runs a Synapse instance as part of its Docker Compose stack
- Guild members have accounts on their guild's homeserver
- Matrix user IDs are `@{player.id}:{guild_homeserver}` (e.g. `@1-42:matrix.guild.example`) — immutable player id from OIDC `sub`
- Guilds that opt out simply don't run a homeserver
- Local rooms (e.g., `#general`) stay within the guild
- Federated rooms (e.g., `#global-trade`) are replicated across all participating homeservers

### Federation Details

Federation is **built into the Matrix protocol** and works on-demand:

- Servers only communicate when they share rooms or users
- No central authority, registry, or coordination is needed
- A guild stands up a homeserver, configures DNS, and can federate immediately
- Federation uses the **Server-Server API** over HTTPS (port 8448 by default)
- Each homeserver has a signing key pair for authenticating federation traffic
- Room state is replicated via a DAG (directed acyclic graph) of events with deterministic state resolution

**Server discovery** works via:
1. `/.well-known/matrix/server` file at the guild's domain
2. DNS SRV record at `_matrix-fed._tcp.{domain}`
3. Fallback to `{domain}:8448`

**Federation can be restricted per guild:**
- Allowlist: only federate with specific servers
- Blocklist: refuse to federate with specific servers
- Disable entirely: fully isolated guild chat

**Room-level server ACLs** allow banning specific servers from specific rooms without affecting the whole homeserver's federation.

---

## Moderation Model

### Power Levels (Per-Room)

Every user in a room has a numeric power level. Actions require configurable minimum levels.

| Level | Typical Role | Abilities                                    |
|-------|-------------|----------------------------------------------|
| 0     | Viewer      | Read only (if events_default > 0)            |
| 10    | Member      | Send messages, reactions                     |
| 25    | Trusted     | Send messages + images/files                 |
| 50    | Moderator   | Kick, mute, redact others' messages          |
| 75    | Officer     | Ban users, change room topic                 |
| 100   | Admin       | Full control, promote/demote others          |

Power levels are fully configurable per room. The thresholds above are examples.

### Room Version 12: Creator Privileges

Room version 12 (introduced August 2025, MSC4289) changed creator semantics in ways that matter for guild governance:

- **The room creator has infinite power level** — permanently and immutably. The creator no longer appears in the power levels `users` map at all; every server and client infers their infinite privilege from the `m.room.create` event. A creator can never be demoted, banned via power levels, or overruled inside their room.
- **`additional_creators`** — the `m.room.create` event can list co-creators who share infinite power. Useful for guild co-leadership, but the list is immutable after creation.
- **Room upgrades require power level 150 by default** — normal admins (100) can no longer upgrade a room and thereby assume creator rights; a creator must explicitly boost someone to 150 to hand over that ability.

**Design consequence for Structs:** rooms should be created by a **long-lived guild bot account** (not a personal player account), since creator privilege is permanent and tied to the creating account. Guild leadership changes then only require reassigning power level 100, not recreating rooms. For cross-guild rooms, agree up front on which account creates the room (or use `additional_creators` for one trusted account per founding guild).

### Three Layers of Moderation

**1. Room-Level Moderation**
- Kick, ban, mute individual users in a specific room
- Any room moderator/admin can do this regardless of which server the target is on
- Redact (delete) specific messages from anyone
- Set rooms to invite-only to control access

**2. Server ACLs (Room-Level Server Bans)**
- A room admin can ban an entire homeserver from a room via `m.room.server_acl`
- All users from that server are removed and cannot rejoin
- Does not require cooperation from the banned server

```json
{
  "type": "m.room.server_acl",
  "content": {
    "allow": ["*"],
    "deny": ["rogue-guild.example.com"],
    "allow_ip_literals": false
  }
}
```

**3. Homeserver-Level Moderation (Guild Admin)**
- Deactivate accounts on the guild's own server
- Block federation with specific servers entirely
- Shadow-ban local users
- Server-wide policies

### Selective Muting / Broadcast Channels

Rooms can be configured so only select users can speak:

- **Broadcast channel:** Set `events_default: 50`, `users_default: 0` — only users promoted to 50+ can send messages
- **Selective mute:** Drop a specific user's power level below `events_default`
- **Per-event-type permissions:** Different power levels for text, reactions, stickers, images, room settings, etc.
- **Join rules:** Public, knock (request to join), invite-only, or restricted (must be member of a specific Space)

### Automated Moderation

**Draupnir** (successor to Mjolnir) is a moderation bot that:
- Maintains ban lists shareable across rooms
- Auto-bans users matching patterns
- Protects rooms from raids (auto-ban on join-rate spikes)
- Supports community ban lists that guilds can opt into voluntarily

This enables cross-guild moderation councils: a shared ban list that participating guilds subscribe to, preserving guild sovereignty while enabling collective defense.

---

## Custom Authentication

### Architecture: MAS + Webapp as OIDC Identity Provider

Matrix authentication has moved to **Matrix Authentication Service (MAS)**, Element's next-generation auth architecture (MSC3861). MAS is now the stable, recommended path for Synapse; legacy password auth provider modules are not supported by MAS and are on a deprecation trajectory. Migration from legacy auth to MAS is one-way.

Rather than writing a custom Synapse auth module (the legacy approach), the design is:

- **The Symfony webapp becomes an OIDC identity provider.** Its "login screen" is the existing Cosmos signature flow — the same message signing and `structsd` validation already implemented in `AuthManager.php` and `SignatureValidationManager.php`. The Cosmos signature remains the one and only credential.
- **MAS delegates to the webapp** as an upstream OIDC provider. MAS handles all Matrix token issuance, session management, and the compatibility layer for older clients.
- **Synapse delegates all auth to MAS** via the stable `matrix_authentication_service` configuration block.

This keeps the signature validation code in PHP where it already exists and is tested, instead of reimplementing it a second time in Python inside Synapse. It also makes login work correctly in next-gen clients like Element X, which only support OIDC-native auth.

### Auth Flow

```mermaid
sequenceDiagram
    participant Client as Chat Client (webapp panel or Element X)
    participant MAS as MAS (per guild)
    participant Webapp as Symfony Webapp (OIDC IdP)
    participant Structsd as structsd
    participant Synapse as Synapse

    Client->>MAS: Start login (OIDC)
    MAS->>Webapp: Redirect to authorize endpoint
    Webapp->>Webapp: Existing Cosmos signature login (sign message)
    Webapp->>Structsd: GET /structs/validate_signature/...
    Structsd-->>Webapp: valid: true
    Webapp-->>MAS: OIDC code + ID token (sub = player.id)
    MAS-->>Client: Matrix access token
    Client->>Synapse: Authenticated requests (token verified via MAS)
```

Two user experiences fall out of this:

- **Embedded webapp chat:** the user is already logged in to the webapp via Cosmos signature, so the OIDC authorization step is silent — the existing webapp session becomes a token grant and the chat panel just works. No second sign-in.
- **Third-party clients (Element X, Element Web, etc.):** the client opens the webapp's login page in a browser, the user signs the challenge with their Cosmos key exactly as they do for webapp login, and is redirected back authenticated.

### How Signature Auth Works Today (Webapp)

The existing webapp authentication flow (see `AuthController.php`, `AuthManager.php`, `SignatureValidationManager.php`):

1. Client-side: user signs a message with their Cosmos private key
2. Client sends `address`, `pubkey`, `signature`, `guild_id`, `unix_timestamp` to the webapp
3. Webapp calls `structsd` API: `GET /structs/validate_signature/{address}/{pubkey}/{signature}/{message}`
4. Message format: `LOGIN_GUILD{guild_id}ADDRESS{address}DATETIME{unix_timestamp}`
5. `structsd` validates the signature and returns `{ "valid": true/false }`
6. On success, webapp creates a session

This flow is unchanged. It becomes the authentication step behind the webapp's new OIDC authorize endpoint.

### New Work in the Webapp: OIDC Provider Endpoints

**Handoff for the webapp team:** see [OIDC-PROVIDER.md](./OIDC-PROVIDER.md) (implemented upstream). Matrix homeserver packaging is this repo — [README.md](./README.md), [docs/SETUP.md](./docs/SETUP.md).

The Symfony webapp exposes a minimal OIDC provider surface:

| Endpoint | Purpose |
|---|---|
| `/.well-known/openid-configuration` | OIDC discovery document |
| `/oauth/authorize` | Authorization endpoint — gated by the existing Cosmos signature login |
| `/oauth/token` | Token endpoint — issues codes/tokens to MAS |
| `/oauth/jwks` | Public keys for ID token verification |
| `/oauth/userinfo` | Claims: `sub` (player.id), profile fields |

Key design decisions (as shipped):

- **`sub` = `player.id`** (immutable). Matrix localpart becomes `@1-42:homeserver`.
- Wallet address is a **profile** claim (`primary_address`), not the subject.
- If the user already has a webapp session, `/oauth/authorize` completes silently; otherwise SPA resume via `/?oidc=<request_id>`.

### MAS Configuration

MAS runs as its own container per guild and is configured with the webapp as its sole upstream provider. Local passwords and registration are disabled — the only way in is via the guild webapp's Cosmos login.

```yaml
# mas config.yaml (excerpt)
upstream_oauth2:
  providers:
    - id: 01STRUCTSWEBAPPIDP0000000
      issuer: "https://guild.structs.game"
      human_name: "Structs Guild Login"
      client_id: "matrix-auth-service"
      client_secret: "${MAS_UPSTREAM_CLIENT_SECRET}"
      scope: "openid"
      claims_imports:
        localpart:
          action: require
          template: "{{ user.sub }}"        # player.id as Matrix localpart
        displayname:
          action: suggest
          template: "{{ user.preferred_username }}"

passwords:
  enabled: false          # no local passwords; Cosmos signature only

account:
  registration:
    enabled: false        # accounts only via upstream (guild webapp)
```

### Synapse Configuration

Synapse delegates all authentication to MAS via the stable configuration block:

```yaml
# homeserver.yaml (excerpt)
matrix_authentication_service:
  enabled: true
  endpoint: "http://structs-mas:8080"
  secret: "${MAS_SYNAPSE_SHARED_SECRET}"
```

With delegation enabled, Synapse's own `/login`, `/register`, and password handling are disabled; MAS provides a compatibility layer so legacy clients that call `/_matrix/client/v3/login` continue to work.

### Client-Side Login (JavaScript)

From the embedded webapp chat, `matrix-js-sdk` uses the OIDC login flow. Since the user already holds a webapp session, the redirect through the authorize endpoint completes without user interaction:

```javascript
import * as sdk from "matrix-js-sdk";

// Discover the homeserver's auth issuer (points at MAS)
const authMetadata = await sdk.discoverAndValidateOIDCIssuerWellKnown(
    "https://matrix.guild.structs.game"
);

// Standard OIDC authorization code flow with PKCE.
// The user's existing webapp session makes this redirect silent.
// On completion the SDK holds a Matrix access token for
// @structs1abc...xyz:guild.structs.game
```

The result is the same as the original design — a Matrix session tied to the player's Cosmos address — but issued through MAS instead of a custom login type.

---

## Docker Integration

No custom containers are needed. Both Synapse and MAS run from stock upstream images; all Structs-specific logic lives in the webapp's OIDC endpoints and in configuration files.

### Directory Structure

```
docker-structs-guild/
├── compose.yaml                      # Add structs-matrix + structs-mas services
└── config/
    └── matrix/
        ├── homeserver.yaml           # Synapse configuration (delegates auth to MAS)
        └── mas-config.yaml           # MAS configuration (upstream = guild webapp)
```

### Compose Services

Add to `compose.yaml`:

```yaml
structs-matrix:
  image: 'ghcr.io/element-hq/synapse:latest'
  hostname: 'structs-matrix'
  restart: on-failure
  volumes:
    - matrix-data:/data
    - ./config/matrix/homeserver.yaml:/data/homeserver.yaml:ro
  ports:
    - ${MATRIX_CLIENT_PORT:-8008}:8008    # Client-Server API
    - ${MATRIX_FEDERATION_PORT:-8448}:8448 # Federation API
  depends_on:
    structs-pg:
      condition: service_healthy
      restart: true
    structs-mas:
      condition: service_started
  environment:
    SYNAPSE_SERVER_NAME: "${MATRIX_SERVER_NAME}"
    SYNAPSE_REPORT_STATS: "no"

structs-mas:
  image: 'ghcr.io/element-hq/matrix-authentication-service:latest'
  hostname: 'structs-mas'
  restart: on-failure
  volumes:
    - ./config/matrix/mas-config.yaml:/config.yaml:ro
  command: ["server", "--config", "/config.yaml"]
  ports:
    - ${MAS_HTTP_PORT:-8081}:8080         # MAS HTTP (auth UI + APIs)
  depends_on:
    structs-pg:
      condition: service_healthy
      restart: true
    structs-webapp:
      condition: service_started          # webapp is the upstream OIDC IdP
```

Add to volumes:

```yaml
volumes:
  matrix-data:
    name: structs-matrix-data
```

Both services use the guild's existing PostgreSQL (`structs-pg`) with their own databases (`structs_matrix` for Synapse, `structs_mas` for MAS). These need to be added to the `structs-pg` initialization scripts.

### Synapse Configuration (homeserver.yaml)

```yaml
# Use the guild's existing PostgreSQL
database:
  name: psycopg2
  args:
    host: structs-pg
    port: 5432
    user: structs_matrix
    password: "${MATRIX_DB_PASSWORD}"
    database: structs_matrix
    cp_min: 5
    cp_max: 10

# Delegate all authentication to MAS (stable integration)
matrix_authentication_service:
  enabled: true
  endpoint: "http://structs-mas:8080"
  secret: "${MAS_SYNAPSE_SHARED_SECRET}"

# Registration and passwords are handled by MAS, not Synapse
enable_registration: false
password_config:
  enabled: false

# Reduce cache for lower memory footprint (optional)
caches:
  global_factor: 0.5
```

### MAS Configuration (mas-config.yaml)

```yaml
http:
  public_base: "https://auth.guild.structs.game"

database:
  uri: "postgresql://structs_mas:${MAS_DB_PASSWORD}@structs-pg:5432/structs_mas"

matrix:
  homeserver: "${MATRIX_SERVER_NAME}"
  endpoint: "http://structs-matrix:8008"
  secret: "${MAS_SYNAPSE_SHARED_SECRET}"

upstream_oauth2:
  providers:
    - id: 01STRUCTSWEBAPPIDP0000000
      issuer: "https://guild.structs.game"
      human_name: "Structs Guild Login"
      client_id: "matrix-auth-service"
      client_secret: "${MAS_UPSTREAM_CLIENT_SECRET}"
      scope: "openid"
      claims_imports:
        localpart:
          action: require
          template: "{{ user.sub }}"
        displayname:
          action: suggest
          template: "{{ user.preferred_username }}"

passwords:
  enabled: false

account:
  registration:
    enabled: false
```

### Proxy Configuration

Add to `structs-proxy` nginx config for federation discovery:

```nginx
# Matrix well-known for federation discovery
location /.well-known/matrix/server {
    return 200 '{"m.server": "${MATRIX_SERVER_NAME}:443"}';
    default_type application/json;
    add_header Access-Control-Allow-Origin *;
}

location /.well-known/matrix/client {
    return 200 '{"m.homeserver": {"base_url": "https://${MATRIX_SERVER_NAME}"}}';
    default_type application/json;
    add_header Access-Control-Allow-Origin *;
}

# Proxy Matrix Client-Server API
location /_matrix {
    proxy_pass http://structs-matrix:8008;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
    client_max_body_size 50M;
}

# Proxy Matrix Federation API
location /_matrix/federation {
    proxy_pass http://structs-matrix:8008;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}

# MAS compatibility layer: legacy clients still call /login, /logout, /refresh
# on the homeserver; these must be routed to MAS instead of Synapse
location ~ ^/_matrix/client/(.*)/(login|logout|refresh) {
    proxy_pass http://structs-mas:8080;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}

# MAS auth UI and OIDC endpoints (on the auth subdomain)
# server_name auth.guild.structs.game
location / {
    proxy_pass http://structs-mas:8080;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}
```

The `.well-known/matrix/client` document should also advertise the auth issuer so clients discover MAS:

```json
{
  "m.homeserver": { "base_url": "https://matrix.guild.structs.game" },
  "org.matrix.msc2965.authentication": {
    "issuer": "https://auth.guild.structs.game/",
    "account": "https://auth.guild.structs.game/account"
  }
}
```

---

## Resource Estimates

| Metric                        | Typical Range                          |
|-------------------------------|----------------------------------------|
| RAM (idle, small guild)       | 300–500 MB                             |
| RAM (active, medium guild)    | 500 MB – 1 GB                          |
| Disk (database, first year)   | 1–5 GB depending on activity           |
| CPU                           | Minimal unless federating large rooms  |

Tunable via `caches.global_factor` in `homeserver.yaml` to reduce memory.

---

## Room Structure Examples

### Guild Announcements (Broadcast)
```
#announcements:alpha.structs.game
├── events_default: 50        (need mod+ to post)
├── users_default: 0          (everyone joins as viewer)
├── Guild leader: level 100
└── Officers: level 50        (can post announcements)
```

### Global Trade Chat (Verified Traders)
```
#global-trade:structs.game
├── events_default: 10        (need level 10 to post)
├── users_default: 0          (join as viewer)
├── Verified traders: level 10
├── Moderators: level 50
└── Admins: level 100
```

### Alliance War Room (Private)
```
#alpha-beta-war-room:alpha.structs.game
├── join_rule: invite         (invite only)
├── events_default: 0         (all invitees can speak)
├── Alliance commanders: level 100
└── Officers from both guilds: level 50
```

### World Event Spectator Channel
```
#world-boss-event:structs.game
├── events_default: 75
├── users_default: 0
├── m.reaction: 0             (anyone can react)
├── Event narrators: level 75
└── Moderators: level 50
```

---

## Implementation Steps

### Phase 1: Webapp OIDC Provider — DONE

Shipped in `structs-webapp` + `structs-pg` (OIDC tables, seed/generate-key commands, infra handoff docs). `sub` = `player.id`.

### Phase 2: Synapse + MAS (this repo) — IN PROGRESS

1. Standalone compose in `structs-tel` joining the guild Docker network
2. DB init on `structs-pg` for `synapse` / `mas` databases (owned here, not Sqitch)
3. Operator docs: SETUP, CREW-REFERENCE, CHECKLIST, guild-compose handoff
4. Validate on `crew.oh.energy`

### Phase 3: Federation / proxy polish

1. Caddy/well-known production wiring (guild proxy team via handoff)
2. Two-guild federation test
3. Server ACLs smoke test

### Phase 4: Clients / moderation (later)

1. Optional in-game `matrix-js-sdk` panel
2. Draupnir, room templates, guild bot as room creator
3. Rank → power level sync (optional)

---

## References

- [Matrix Specification](https://spec.matrix.org/)
- [Synapse Documentation](https://element-hq.github.io/synapse/latest/)
- [Matrix Authentication Service](https://element-hq.github.io/matrix-authentication-service/)
- [MAS Upstream OIDC Setup](https://element-hq.github.io/matrix-authentication-service/setup/sso.html)
- [MSC3861: Next-Generation Auth](https://github.com/matrix-org/matrix-spec-proposals/pull/3861)
- [MSC4289: Explicitly Privilege Room Creators (room v12)](https://github.com/matrix-org/matrix-spec-proposals/blob/main/proposals/4289-privilege-creators.md)
- [August 2025 Security Release (room v12, CVE-2025-49090)](https://matrix.org/blog/2025/08/security-release/)
- [Synapse Docker Image (element-hq)](https://ghcr.io/element-hq/synapse)
- [matrix-js-sdk](https://github.com/matrix-org/matrix-js-sdk)
- [matrix-widget-toolkit](https://github.com/nordeck/matrix-widget-toolkit)
- [Tuwunel Homeserver](https://github.com/matrix-construct/tuwunel)
- [Draupnir Moderation Bot](https://github.com/the-draupnir-project/Draupnir)
- [Existing Guild Docker Compose](https://github.com/playstructs/docker-structs-guild/blob/main/compose.yaml)
- [Existing Webapp Auth](https://github.com/playstructs/structs-webapp/blob/main/src/src/Controller/AuthController.php)
