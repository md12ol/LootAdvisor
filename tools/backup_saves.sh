#!/usr/bin/env bash
# Thin wrapper: all options are passed to backup_saves.py (see: backup_saves.sh --help).
exec "${PYTHON:-python}" "$(dirname "$0")/backup_saves.py" "$@"
