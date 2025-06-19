#!/usr/bin/env bash

# Get the absolute path of the directory where the script is located
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)


cd $SCRIPT_DIR

#mkdir "${SCRIPT_DIR}/bui"

#git@github.com:rgnets/baresip.git
rm -rf  "${SCRIPT_DIR}/_baresip"
git clone --depth 1 --branch rgnets-custom git@github.com:rgnets/baresip.git "${SCRIPT_DIR}/_baresip"
cd "${SCRIPT_DIR}/_baresip"

cmake -B build -DCMAKE_BUILD_TYPE=Release -DAPP_MODULES_DIR=./modules -DAPP_MODULES="rgrtcpsummary"
cmake --build build -j