#!/bin/sh
cd "$(dirname "$0")" || exit 1

cd ../
pip --require-virtualenv install -r requirements.txt
pip --require-virtualenv install -r requirements-dev.txt

apt satisfy   libcairo2-dev, \
               libdbus-1-3, \
               libdbus-1-dev, \
               libdbus-glib-1-dev, \
               libffi-dev, \
               libgirepository1.0-dev, \
               libglib2.0-0, \
               libglib2.0-dev