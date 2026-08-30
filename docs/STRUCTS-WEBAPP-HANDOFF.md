# Handoff: structs-webapp (Matrix / MAS OIDC)

From the crew.oh.energy Matrix bring-up (`structs-tel`, 2026-08-28).  
Please land these in **structs-webapp** so guilds do not rediscover them.

## 1. Required: integer `iat` / `exp` on ID tokens

### Symptom

After wallet login, MAS upstream callback fails:

```text
Unexpected error
invalid claim "exp"
```

MAS log:

```text
ERROR mas_axum_utils::fancy_error: invalid claim "exp"
GET /upstream/callback/<provider_id> → 500
```

### Cause

`lcobucci/jwt` 5.x encodes `DateTimeImmutable` **with microseconds**, so ID tokens look like:

```json
{"iat": 1787928562.571061, "exp": 1787932162.571061}
```

Matrix Authentication Service (`openidconnect-rs`) expects JWT **NumericDate** claims as **whole seconds** (JSON integers). Fractional `exp` / `iat` are rejected as `invalid claim "exp"`.

### Fix

In `src/Oidc/IdTokenResponse.php` (`buildIdToken`), truncate times to second precision before `issuedAt` / `expiresAt`:

```php
// MAS / openidconnect-rs reject non-integer NumericDate claims
// (lcobucci/jwt emits fractional seconds from DateTimeImmutable microseconds).
$issuedAt = (new DateTimeImmutable())->setTimestamp(time());
$expiresAt = DateTimeImmutable::createFromInterface($accessToken->getExpiryDateTime())
    ->setTimestamp($accessToken->getExpiryDateTime()->getTimestamp());
$claims = $this->claimsManager->buildClaims($player, $scopes);

$builder = $this->jwtConfiguration()->builder()
    ->issuedBy($this->config->getIssuer())
    ->permittedFor($accessToken->getClient()->getIdentifier())
    ->relatedTo($claims['sub'])
    ->issuedAt($issuedAt)
    ->expiresAt($expiresAt)
    ->withHeader('kid', $this->config->getKeyId());
```

Replace the previous:

```php
$issuedAt = new DateTimeImmutable();
// ...
->issuedAt($issuedAt)
->expiresAt($accessToken->getExpiryDateTime())
```

### Verify

Decode a freshly issued `id_token` payload (middle JWT segment). `iat` and `exp` must be integers, e.g. `1787928562`, not `1787928562.571061`.

Optional unit/integration assertion: JSON-encode the claims map and assert `is_int($payload['exp']) && is_int($payload['iat'])`.

Crew applied this live under `~/structs-webapp/src/src/Oidc/IdTokenResponse.php` via `structs-tel/scripts/crew-fix-id-token-numericdate.py` — that is a hotfix only; please commit the equivalent in git.

---

## 1b. Ops: OIDC client secret must be hex (not base64)

### Symptom

After wallet login, MAS upstream callback fails with a generic 500. MAS log:

```text
Request to the token endpoint failed
"invalid_client": Client authentication failed
GET /upstream/callback/<provider_id> → 500
```

`curl` with raw HTTP Basic against `/oauth/token` may return `invalid_grant` (secret accepted) while MAS still 401s.

### Cause

MAS `token_endpoint_auth_method: client_secret_basic` percent-encodes the secret before Base64 (RFC 6749 §2.3.1). `league/oauth2-server` `AbstractGrant::getBasicAuthCredentials` does not urldecode. `openssl rand -base64 32` commonly emits `+`, `/`, `=`.

### Fix (ops, any guild)

Use hex: `openssl rand -hex 32`. Put the same value in structs-tel `.env` and webapp `.env`, re-run `app:oidc:seed-client`, re-render MAS, recreate the MAS container. Re-seeding the old secret does not help.

### Suggested product improvement

In `getBasicAuthCredentials` (or a wrapper), `rawurldecode` the Basic username and password so RFC-encoded secrets still verify. structs-tel generators now emit hex so new deploys do not depend on that.

---

## 2. Ops: `app:oidc:generate-key` file ownership

### Symptom

`GET /oauth/authorize` → **500**

```text
LogicException: Key path "file:///src/config/oidc/private.key" does not exist or is not readable
```

### Cause

`php bin/console app:oidc:generate-key` (often as root in Docker) writes:

```text
config/oidc/private.key  root:root  0600
config/oidc/public.key   root:root  0644
```

The PHP-FPM / Apache user (`www-data`) cannot read the private key.

### Fix (runtime)

```bash
chown www-data:www-data config/oidc/private.key config/oidc/public.key
chmod 640 config/oidc/private.key
chmod 644 config/oidc/public.key
```

### Suggested product improvement

Have `app:oidc:generate-key` (or its docs) ensure the private key is readable by the web server user, or print an explicit post-step. Document in the Matrix OIDC handoff under `structs-webapp/docs/`.

---

## 3. Confirmed working contract (for regression)

These already match what MAS needs on crew; keep them stable:

| Item | Value / behaviour |
|---|---|
| Issuer | Public HTTPS origin, no trailing slash (e.g. `https://crew.oh.energy`) |
| `sub` | `player.id` (e.g. `1-42`) — Matrix localpart |
| Scopes | `openid profile` |
| PKCE | S256 required |
| Client | Confidential; seed with exact MAS callback URI |
| Cold login | Unauthenticated authorize → `302` → `/?oidc=<request_id>` → wallet SPA → resume |
| Redirect URI | Byte-for-byte match, including path and trailing-slash rules |

Example seed (after MAS upstream provider id is known):

```bash
php bin/console app:oidc:seed-client \
  --redirect-uri='https://auth.EXAMPLE/upstream/callback/<MAS_UPSTREAM_PROVIDER_ID>'
```

---

## 4. Checklist for the webapp PR

- [ ] Patch `IdTokenResponse` NumericDate (section 1)
- [ ] Test: issued `id_token` has integer `iat`/`exp`
- [ ] Test or doc: key files readable by runtime user after `generate-key` (section 2)
- [ ] Note in existing `docs/matrix-oidc-*-handoff.md`: MAS rejects fractional NumericDate
- [ ] No change required to `sub` / claims mapping unless you diverge from `player.id`

---

## 5. Optional: fleet room ensure after first Matrix login

Day-2 ops create public fleet rooms as `@guild-bot` (`#fleet-9-N` ↔ player `1-N`) via `structs-tel/scripts/ensure-fleet-room.py`. A future webapp hook can call that script (or the same Client-Server createRoom flow with the guild-bot token) after a player’s first successful Matrix session.

Do **not** create fleet rooms as the player — room v12 makes the creator permanently infinitely privileged. Keep ensure idempotent and server-side.

Not required for the NumericDate / key-permission PR above.

## 6. Out of scope for webapp (FYI)

Handled in `structs-tel` / guild infra, not this PR:

- Synapse + MAS compose, DB init, Caddy for `matrix.` / `auth.`
- `structs-pg` TLS must be X.509 **v3** (MAS rustls rejects v1 certs)
- Synapse volume ownership uid 991; `allow_unsafe_locale` for C.UTF-8 Postgres
- MSC4108 / public room directory / guild-bot token storage — see `structs-tel/docs/UPGRADE.md`

Full diary: `structs-tel/docs/CREW-REFERENCE.md`.
