#!/usr/bin/env bash
# Fully containerized run: builds the app image and runs pytest inside compose.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE="docker compose -p llm-tg-assistant-test -f docker-compose.test.yml --profile runner"
trap '$COMPOSE down -v >/dev/null 2>&1 || true' EXIT
$COMPOSE build test-runner
$COMPOSE run --rm test-runner python -m pytest "$@"
