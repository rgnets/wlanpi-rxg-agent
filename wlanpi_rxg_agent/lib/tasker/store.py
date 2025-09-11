import json
import os
from typing import Any, Dict, List

STATE_DIR = "/var/lib/wlanpi-rxg-agent"
STATE_PATH = os.path.join(STATE_DIR, "tasks.json")


def _ensure_dir():
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
    except Exception:
        # In constrained environments, fall back to current directory
        pass


def load_snapshot() -> Dict[str, List[dict]]:
    _ensure_dir()
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
            # Basic shape normalization
            return {
                "ping_targets": data.get("ping_targets", []),
                "traceroutes": data.get("traceroutes", []),
                "sip_tests": data.get("sip_tests", []),
            }
    except FileNotFoundError:
        return {"ping_targets": [], "traceroutes": [], "sip_tests": []}
    except Exception:
        return {"ping_targets": [], "traceroutes": [], "sip_tests": []}


def save_snapshot(snapshot: Dict[str, List[dict]]) -> None:
    _ensure_dir()
    tmp_path = f"{STATE_PATH}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(snapshot, f)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp_path, STATE_PATH)
