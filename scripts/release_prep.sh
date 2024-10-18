#!/bin/sh
cd "$(dirname "$0")" || exit 1

set -x

echo "Updating requirements"
./generate_requirements.sh

echo "Formatting..."
./format.sh

echo "Linting..."
./lint.sh

echo "Generating manpage... (Have you updated the manpage?)"
./manpage.sh

echo ""