#!/usr/bin/env bash
# Thin wrapper: all options are passed to restore_saves.py (see: restore_saves.sh --help).
exec "${PYTHON:-python}" "$(dirname "$0")/restore_saves.py" "$@"
