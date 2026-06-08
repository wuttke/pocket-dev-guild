#!/usr/bin/env bash
# Run the Pocket Dev Guild backend (FastAPI / uvicorn) bound to all
# interfaces so containerized clients (e.g. the dockerized nginx in the
# remix-of-frontend-guild-prep compose setup) can reach it via the docker
# host-gateway alias `host.docker.internal`.
#
# Usage (manual, from any cwd):
#     nohup /path/to/pocket-dev-guild/run-dev.sh \
#         > /tmp/pdg-uvicorn.log 2>&1 &
#
# Extra args are forwarded to uvicorn, e.g.:
#     ./run-dev.sh --reload
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

exec .venv/bin/uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    "$@"
