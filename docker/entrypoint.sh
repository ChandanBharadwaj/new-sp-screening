#!/usr/bin/env sh
set -e

# Derive a JDBC URL from DATABASE_URL_SYNC if LIQUIBASE_COMMAND_URL is not set.
# Expected DATABASE_URL_SYNC form: postgresql://user:pass@host:port/db
if [ -z "${LIQUIBASE_COMMAND_URL:-}" ] && [ -n "${DATABASE_URL_SYNC:-}" ]; then
    rest="${DATABASE_URL_SYNC#*://}"
    creds="${rest%@*}"
    hostpart="${rest#*@}"
    LIQUIBASE_COMMAND_USERNAME="${LIQUIBASE_COMMAND_USERNAME:-${creds%%:*}}"
    LIQUIBASE_COMMAND_PASSWORD="${LIQUIBASE_COMMAND_PASSWORD:-${creds#*:}}"
    LIQUIBASE_COMMAND_URL="jdbc:postgresql://${hostpart}"
    export LIQUIBASE_COMMAND_URL LIQUIBASE_COMMAND_USERNAME LIQUIBASE_COMMAND_PASSWORD
fi

echo "[entrypoint] running liquibase update against ${LIQUIBASE_COMMAND_URL}"
liquibase --defaults-file=/app/liquibase.properties update

exec "$@"
