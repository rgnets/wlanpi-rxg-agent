#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"/../ || exit 1
set -x

export PYTHONPATH="${PYTHONPATH:-.}:."
python -m pytest -m "not integration and not hardware and not slow" \
  wlanpi_rxg_agent/tests \
  wlanpi_rxg_agent/lib/*/tests \
  "${@}"
