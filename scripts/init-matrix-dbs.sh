#!/bin/sh
# Create Synapse + MAS databases and roles on an existing structs-pg instance.
# Intended to run from the matrix-db-init compose service (profile: init),
# or manually:
#   docker compose --profile init run --rm matrix-db-init
#
# Auth note (crew / structs-pg):
# - Known Structs roles use hostssl + trust on database "structs" only.
# - New roles authenticate with passwords via hostssl md5 (or scram).
# - This script connects as MATRIX_DB_ADMIN_USER (default: structs) to the
#   admin database (default: structs) over the Docker network.

set -eu

: "${PGHOST:?}"
: "${PGPORT:?}"
: "${PGUSER:?}"
: "${PGDATABASE:?}"
: "${SYNAPSE_DB_NAME:?}"
: "${SYNAPSE_DB_USER:?}"
: "${SYNAPSE_DB_PASSWORD:?}"
: "${MAS_DB_NAME:?}"
: "${MAS_DB_USER:?}"
: "${MAS_DB_PASSWORD:?}"

export PGPASSWORD="${PGPASSWORD:-}"
# structs-pg requires SSL for Docker-network clients (hostssl ... trust/md5)
export PGSSLMODE="${PGSSLMODE:-require}"

echo "Waiting for Postgres at ${PGHOST}:${PGPORT}..."
i=0
until psql -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "Postgres not reachable" >&2
    exit 1
  fi
  sleep 2
done

echo "Ensuring roles and databases exist..."

psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${SYNAPSE_DB_USER}') THEN
    CREATE ROLE ${SYNAPSE_DB_USER} LOGIN PASSWORD '${SYNAPSE_DB_PASSWORD}';
  ELSE
    ALTER ROLE ${SYNAPSE_DB_USER} WITH LOGIN PASSWORD '${SYNAPSE_DB_PASSWORD}';
  END IF;

  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${MAS_DB_USER}') THEN
    CREATE ROLE ${MAS_DB_USER} LOGIN PASSWORD '${MAS_DB_PASSWORD}';
  ELSE
    ALTER ROLE ${MAS_DB_USER} WITH LOGIN PASSWORD '${MAS_DB_PASSWORD}';
  END IF;
END
\$\$;
SQL

# CREATE DATABASE cannot run inside a DO block
DB_EXISTS="$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${SYNAPSE_DB_NAME}'")"
if [ "$DB_EXISTS" != "1" ]; then
  psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${SYNAPSE_DB_NAME} OWNER ${SYNAPSE_DB_USER}"
else
  psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE ${SYNAPSE_DB_NAME} OWNER TO ${SYNAPSE_DB_USER}"
fi

DB_EXISTS="$(psql -tAc "SELECT 1 FROM pg_database WHERE datname = '${MAS_DB_NAME}'")"
if [ "$DB_EXISTS" != "1" ]; then
  psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${MAS_DB_NAME} OWNER ${MAS_DB_USER}"
else
  psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE ${MAS_DB_NAME} OWNER TO ${MAS_DB_USER}"
fi

psql -v ON_ERROR_STOP=1 <<SQL
GRANT ALL PRIVILEGES ON DATABASE ${SYNAPSE_DB_NAME} TO ${SYNAPSE_DB_USER};
GRANT ALL PRIVILEGES ON DATABASE ${MAS_DB_NAME} TO ${MAS_DB_USER};
SQL

echo "Matrix databases ready:"
psql -c "\l ${SYNAPSE_DB_NAME}"
psql -c "\l ${MAS_DB_NAME}"
