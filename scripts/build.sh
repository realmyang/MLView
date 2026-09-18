#!/usr/bin/env sh
set -e
MLVIEW_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$MLVIEW_ROOT/scripts/pythonpick.sh"
mlview_pick_python
exec "$PYTHON" "$MLVIEW_ROOT/scripts/check.py" build "$@"
