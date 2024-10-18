#!/usr/bin/env bash
cd "$(dirname "$0")"/../ || exit 1
set -x

autoflake --remove-all-unused-imports --recursive --remove-unused-variables --in-place wlanpi_rxg_agent --exclude=__init__.py
black wlanpi_rxg_agent
isort wlanpi_rxg_agent