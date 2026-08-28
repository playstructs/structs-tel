#!/usr/bin/env bash
# Render Synapse + MAS config templates (delegates to render-configs.py so MAS
# multiline secrets inject correctly).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${MATRIX_SERVER_NAME:?}"
: "${SYNAPSE_PUBLIC_BASEURL:?}"
: "${MAS_PUBLIC_BASE:?}"
: "${OIDC_ISSUER:?}"
: "${OIDC_MAS_CLIENT_ID:?}"
: "${OIDC_MAS_CLIENT_SECRET:?}"
: "${MAS_UPSTREAM_PROVIDER_ID:?}"
: "${MAS_SYNAPSE_SHARED_SECRET:?}"
: "${SYNAPSE_DB_PASSWORD:?}"
: "${MAS_DB_PASSWORD:?}"

if [ ! -f config/secrets/mas-secrets.yaml ]; then
  echo "Missing config/secrets/mas-secrets.yaml — run ./scripts/generate-secrets.sh" >&2
  exit 1
fi

python3 scripts/render-configs.py

echo "Remember: Synapse data volume must be writable by uid 991 (media_store)."
echo "  docker run --rm -v structs-matrix-synapse-data:/data alpine chown -R 991:991 /data"
