#!/usr/bin/env bash
# Retained as a command-line entrypoint; URLs and versions are caller supplied.
set -Eeuo pipefail
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python "$script_directory/../../actions/release-tools/docs.py" "$@"
