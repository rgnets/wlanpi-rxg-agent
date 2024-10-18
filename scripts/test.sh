#!/usr/bin/env bash

set -e
set -x

pytest --cov=app --cov-report=term-missing wlanpi_rxg_agent/tests "${@}"