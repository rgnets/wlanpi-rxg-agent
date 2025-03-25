#!/bin/bash
cd "$(dirname "$0")"/../ || exit 1
set -euxo pipefail
VENV="../wlanpi-rxg-agent-venv"

ssh root@192.168.30.17 "pip install gunicorn virtualenv"
rsync -rav ./ root@192.168.30.17:/tmp/wlanpi-rxg-agent --exclude=openwrt/ --exclude=.git/ --exclude=.mypy_cache/ --exclude=.idea/
ssh root@192.168.30.17 "cd /tmp/wlanpi-rxg-agent; virtualenv --system-site-packages $VENV -p /usr/bin/python3 && source $VENV/bin/activate && pip install -r requirements.txt"