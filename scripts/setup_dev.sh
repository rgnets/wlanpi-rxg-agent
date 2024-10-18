#!/bin/sh
cd "$(dirname "$0")" || exit 1

cd ../
pip --require-virtualenv install -r requirements.txt
pip --require-virtualenv install -r requirements-dev.txt