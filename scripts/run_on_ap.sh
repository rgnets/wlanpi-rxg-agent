#!/bin/bash
cd "$(dirname "$0")"/../ || exit 1
set -euxo pipefail
VENV="../wlanpi-rxg-agent-venv"

./scripts/sync_to_ap.sh
ssh root@192.168.30.17 "cd /tmp/wlanpi-rxg-agent && source $VENV/bin/activate && uvicorn wlanpi_rxg_agent.rxg_agent:app --reload --host 0.0.0.0 --port 8200"