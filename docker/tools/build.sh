#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
docker build -t wlanpi-rxg-agent-tools .