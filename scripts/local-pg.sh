#!/usr/bin/env bash
# Throwaway PostgreSQL 16 for environments without a Docker daemon (e.g. Claude Code on the web).
# Mirrors the compose `test` profile: superuser owner, DML-only runtime role from 01-roles.sh.
#   scripts/local-pg.sh start   # prints the TEST_DATABASE_* exports
#   scripts/local-pg.sh stop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGBIN="${PGBIN:-$(ls -d /usr/lib/postgresql/16/bin 2>/dev/null || dirname "$(command -v pg_ctl)")}"
DIR="${LOCAL_PG_DIR:-/var/tmp/frontdesk-pg}"
PORT="${LOCAL_PG_PORT:-55433}"
OWNER=frontdesk_owner OWNER_PW=owner-local APP=frontdesk_app APP_PW=app-local DB=frontdesk

as_pg() { if [[ $(id -u) == 0 ]]; then su postgres -c "$*"; else bash -c "$*"; fi; }

case "${1:-start}" in
  start)
    if [[ ! -d "$DIR/data" ]]; then
      mkdir -p "$DIR"; [[ $(id -u) == 0 ]] && chown postgres "$DIR"
      as_pg "$PGBIN/initdb -D $DIR/data -U $OWNER --auth=trust -E UTF8" >/dev/null
      fresh=1
    fi
    as_pg "$PGBIN/pg_ctl -D $DIR/data status" >/dev/null 2>&1 || \
      as_pg "$PGBIN/pg_ctl -D $DIR/data -w -l $DIR/log -o \"-p $PORT -k $DIR -c listen_addresses=127.0.0.1\" start" >/dev/null
    if [[ -n "${fresh:-}" ]]; then
      psql -q -h 127.0.0.1 -p "$PORT" -U "$OWNER" -d postgres -c "CREATE DATABASE $DB"
      POSTGRES_USER=$OWNER POSTGRES_DB=$DB APP_DB_USER=$APP APP_DB_PASSWORD=$APP_PW PGHOST=127.0.0.1 PGPORT=$PORT \
        sh "$ROOT/deploy/postgres/init/01-roles.sh" >/dev/null
    fi
    echo "export TEST_DATABASE_URL=postgresql://$APP:$APP_PW@127.0.0.1:$PORT/$DB"
    echo "export TEST_DATABASE_OWNER_URL=postgresql://$OWNER:$OWNER_PW@127.0.0.1:$PORT/$DB"
    ;;
  stop) as_pg "$PGBIN/pg_ctl -D $DIR/data -m fast stop" ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
