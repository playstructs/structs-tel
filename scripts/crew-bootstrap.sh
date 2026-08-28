#!/usr/bin/env bash
# One-shot crew bootstrap helper (safe to re-run for secrets only if .env missing).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists — not overwriting. Continuing with signing key / render only."
else
  ULID="01$(openssl rand -hex 16 | tr '[:lower:]' '[:upper:]' | head -c 24)"
  # Crockford-ish: strip ILOU
  ULID="$(echo "$ULID" | tr 'ILOU' 'JLMV')"

  cat > .env <<EOF
GUILD_DOCKER_NETWORK=docker-structs-guild_default
MATRIX_SERVER_NAME=matrix.crew.oh.energy
SYNAPSE_PUBLIC_BASEURL=https://matrix.crew.oh.energy/
MAS_PUBLIC_BASE=https://auth.crew.oh.energy/
OIDC_ISSUER=https://crew.oh.energy
MAS_UPSTREAM_PROVIDER_ID=${ULID}
OIDC_MAS_CLIENT_ID=matrix-auth-service
OIDC_MAS_CLIENT_SECRET=$(openssl rand -base64 32 | tr -d '\n')
MAS_SYNAPSE_SHARED_SECRET=$(openssl rand -hex 32)
STRUCTS_PG_HOST=structs-pg
STRUCTS_PG_PORT=5432
MATRIX_DB_ADMIN_USER=structs
MATRIX_DB_ADMIN_DATABASE=structs
SYNAPSE_DB_NAME=synapse
SYNAPSE_DB_USER=synapse
SYNAPSE_DB_PASSWORD=$(openssl rand -hex 24)
MAS_DB_NAME=mas
MAS_DB_USER=mas
MAS_DB_PASSWORD=$(openssl rand -hex 24)
REGISTRATION_SHARED_SECRET=$(openssl rand -hex 32)
MACAROON_SECRET_KEY=$(openssl rand -hex 32)
FORM_SECRET=$(openssl rand -hex 32)
MAS_HTTP_BIND=127.0.0.1
MAS_HTTP_PORT=8081
SYNAPSE_CLIENT_BIND=127.0.0.1
SYNAPSE_CLIENT_PORT=8008
SYNAPSE_FEDERATION_BIND=0.0.0.0
SYNAPSE_FEDERATION_PORT=8448
EOF
  echo "Wrote .env (ULID=${ULID})"
fi

mkdir -p config/secrets
chmod +x scripts/*.sh

if [ ! -f config/secrets/signing.key ]; then
  echo "Generating Synapse signing key..."
  TMP=$(mktemp -d)
  docker run --rm \
    -v "${TMP}:/data" \
    -e SYNAPSE_SERVER_NAME=matrix.crew.oh.energy \
    -e SYNAPSE_REPORT_STATS=no \
    ghcr.io/element-hq/synapse:latest generate
  KEY=$(find "${TMP}" -name '*.signing.key' | head -1)
  cp "${KEY}" config/secrets/signing.key
  chmod 600 config/secrets/signing.key
  rm -rf "${TMP}"
  echo "Wrote config/secrets/signing.key"
else
  echo "signing.key already present"
fi

# envsubst
if ! command -v envsubst >/dev/null 2>&1; then
  echo "Installing gettext-base for envsubst (needs root) — falling back to python render"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  python3 scripts/render-configs.py
else
  ./scripts/render-configs.sh
fi

echo "Bootstrap files ready."
