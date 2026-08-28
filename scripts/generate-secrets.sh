#!/usr/bin/env bash
# Generate secrets and Synapse signing material for a new guild Matrix deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/config/secrets"
SYNAPSE_DATA_TMP="${OUT}/synapse-generate"

mkdir -p "${OUT}"

SERVER_NAME="${MATRIX_SERVER_NAME:-matrix.example.structs.game}"

echo "Generating random secrets into ${OUT} (gitignored)..."
openssl rand -hex 32 > "${OUT}/mas_synapse_shared_secret.txt"
openssl rand -hex 32 > "${OUT}/synapse_db_password.txt"
openssl rand -hex 32 > "${OUT}/mas_db_password.txt"
openssl rand -hex 32 > "${OUT}/registration_shared_secret.txt"
openssl rand -hex 32 > "${OUT}/macaroon_secret_key.txt"
openssl rand -hex 32 > "${OUT}/form_secret.txt"
openssl rand -base64 32 > "${OUT}/oidc_mas_client_secret.txt"

if [ ! -f "${OUT}/mas-secrets.yaml" ]; then
  echo "Generating MAS secrets block via mas-cli config generate..."
  # stderr has progress logs; YAML is on stdout
  docker run --rm --entrypoint mas-cli \
    "${MAS_IMAGE:-ghcr.io/element-hq/matrix-authentication-service:latest}" \
    config generate 2>/dev/null | awk '
      /^secrets:/ {p=1}
      p && /^[a-z]/ && !/^secrets:/ {exit}
      p {print}
    ' > "${OUT}/mas-secrets.yaml"
  if ! grep -q '^secrets:' "${OUT}/mas-secrets.yaml"; then
    echo "Failed to extract MAS secrets block" >&2
    exit 1
  fi
  echo "Wrote ${OUT}/mas-secrets.yaml (keep forever — rotating invalidates sessions)"
else
  echo "Keeping existing ${OUT}/mas-secrets.yaml"
fi

echo "Generating Synapse signing key via official image..."
rm -rf "${SYNAPSE_DATA_TMP}"
mkdir -p "${SYNAPSE_DATA_TMP}"
docker run --rm \
  -v "${SYNAPSE_DATA_TMP}:/data" \
  -e SYNAPSE_SERVER_NAME="${SERVER_NAME}" \
  -e SYNAPSE_REPORT_STATS=no \
  "${SYNAPSE_IMAGE:-ghcr.io/element-hq/synapse:latest}" generate

# Homeserver generate writes <server_name>.signing.key and homeserver.yaml
SIGNING_KEY="$(find "${SYNAPSE_DATA_TMP}" -name '*.signing.key' | head -1)"
if [ -z "${SIGNING_KEY}" ]; then
  echo "Could not find signing key in ${SYNAPSE_DATA_TMP}" >&2
  exit 1
fi
cp "${SIGNING_KEY}" "${OUT}/signing.key"

cat > "${OUT}/.env.generated" <<EOF
# Paste/merge into .env (do not commit)
SYNAPSE_DB_PASSWORD=$(cat "${OUT}/synapse_db_password.txt")
MAS_DB_PASSWORD=$(cat "${OUT}/mas_db_password.txt")
MAS_SYNAPSE_SHARED_SECRET=$(cat "${OUT}/mas_synapse_shared_secret.txt")
OIDC_MAS_CLIENT_SECRET=$(cat "${OUT}/oidc_mas_client_secret.txt")
REGISTRATION_SHARED_SECRET=$(cat "${OUT}/registration_shared_secret.txt")
MACAROON_SECRET_KEY=$(cat "${OUT}/macaroon_secret_key.txt")
FORM_SECRET=$(cat "${OUT}/form_secret.txt")
EOF

chmod 600 "${OUT}/signing.key" "${OUT}/mas-secrets.yaml" "${OUT}/.env.generated" "${OUT}"/*.txt

echo "Done."
echo "  signing key: ${OUT}/signing.key"
echo "  MAS secrets: ${OUT}/mas-secrets.yaml"
echo "  env snippet: ${OUT}/.env.generated"
echo "Compose mounts config/secrets/signing.key; fix volume ownership if Synapse cannot write media_store (uid 991)."
echo "See docs/SETUP.md"
