#!/usr/bin/env bash
# Runs the whole test suite against a disposable Postgres container.
# Extra arguments are forwarded to pytest: bash scripts/test.sh -k outbox -v
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -p llm-tg-assistant-test -f docker-compose.test.yml"   # own project name: never touches the production stack
PY="${PYTHON:-.venv/bin/python}"
PORT="${TEST_DB_PORT:-55432}"
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql://app:app@localhost:${PORT}/app_test}"

started=0
if ! $COMPOSE ps --status running db-test 2>/dev/null | grep -q db-test; then
  $COMPOSE up -d db-test >/dev/null
  started=1
fi
cleanup() {
  if [ "$started" = 1 ]; then $COMPOSE down -v >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  if $COMPOSE exec -T db-test pg_isready -U app -d app_test >/dev/null 2>&1; then break; fi
  sleep 1
done
$COMPOSE exec -T db-test pg_isready -U app -d app_test >/dev/null

"$PY" -m pytest "$@"
