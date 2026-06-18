#!/usr/bin/env bash
# 5-minute load / flow / correctness test bundle.
# Runs the full recipe (selftest → reset+seed → load → cleanup → invariants → report) using the
# `demo` profile (1000 leads / 5 min / 75 attorneys / cap 10 / 10s processing).
#
# Prereqs: the stack is up with the email backend wired (e.g. `docker compose up`) AND the backend
# started with a raised rate limit (RATE_LIMIT_MAX) so intake isn't throttled, e.g.:
#   RATE_LIMIT_MAX=1000000 docker compose up -d
#
# Usage (from anywhere):
#   BASE_URL=http://localhost:8000 ./backend/tests/load/run_5min.sh
# Extra flags pass through, e.g.  ./run_5min.sh --duration 240
set -euo pipefail
cd "$(dirname "$0")/../.."                     # -> backend/
BASE_URL="${BASE_URL:-http://localhost:8000}"
PY="${PY:-./venv/bin/python}"

echo "▶ 5-minute load/flow/correctness test against ${BASE_URL}"
LOAD_TEST=1 "$PY" -m tests.load.run --profile demo --base-url "$BASE_URL" --skip-pytest --force "$@"
code=$?
echo "▶ done (exit ${code}). Report: backend/tests/load/reports/ (latest run-*.md)"
exit ${code}
