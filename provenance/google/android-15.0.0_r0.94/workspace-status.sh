#!/bin/sh
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
cat "$SCRIPT_DIR/workspace-status.txt"
