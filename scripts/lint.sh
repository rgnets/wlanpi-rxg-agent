#!/usr/bin/env bash
cd "$(dirname "$0")"/../ || exit 1

set -x

mypy wlanpi_rxg_agent
black wlanpi_rxg_agent --check
isort --check-only wlanpi_rxg_agent
flake8 wlanpi_rxg_agent