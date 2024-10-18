#!/bin/bash
cd "$(dirname "$0")" || exit 1
# clean pycache
find ../. -regex '^.*\(__pycache__\|\.py[co]\)$' -delete
