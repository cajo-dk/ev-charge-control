#!/usr/bin/with-contenv sh
set -eu

export PYTHONPATH="/app/src"
exec python3 -m evcc
