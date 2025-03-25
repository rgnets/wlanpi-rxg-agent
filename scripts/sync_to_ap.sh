#!/bin/bash
cd "$(dirname "$0")"/../ || exit 1
set -euxo pipefail
VENV="../wlanpi-rxg-agent-venv"

rsync -rav ./ root@192.168.30.17:/tmp/wlanpi-rxg-agent --exclude=openwrt/ --exclude=.git/ --exclude=.mypy_cache/ --exclude=.idea/
