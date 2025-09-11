#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"/../ || exit 1

export PYTHONPATH="${PYTHONPATH:-.}:."

python - <<'PY'
import importlib, sys

modules = [
    "wlanpi_rxg_agent",
    "wlanpi_rxg_agent.lib.logging_utils",
    "wlanpi_rxg_agent.lib.configuration.config_file",
    "wlanpi_rxg_agent.lib.configuration.agent_config_file",
    "wlanpi_rxg_agent.lib.configuration.bridge_config_file",
    "wlanpi_rxg_agent.lib.rxg_supplicant.supplicant",
    "wlanpi_rxg_agent.lib.tasker.tasker",
]

failed = []
for m in modules:
    try:
        importlib.import_module(m)
    except Exception as e:
        print(f"[IMPORT ERROR] {m}: {e}", file=sys.stderr)
        failed.append(m)

if failed:
    print(f"Import check failed for {len(failed)} module(s): {', '.join(failed)}", file=sys.stderr)
    sys.exit(1)
else:
    print(f"Import check passed for {len(modules)} modules")
PY

