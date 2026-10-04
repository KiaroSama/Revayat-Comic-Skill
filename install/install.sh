#!/usr/bin/env bash
# Native entry point; transaction and logging behavior live in safe_install.py.
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="${REVAYAT_PYTHON:-}"
if [ -z "$python" ]; then
    if command -v python3 >/dev/null 2>&1; then python=python3
    elif command -v python >/dev/null 2>&1; then python=python
    fi
fi
if [ -z "$python" ] || ! "$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    printf '%s [ERROR] [installer] Python 3.10+ is required; set REVAYAT_PYTHON to its executable.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >&2
    exit 1
fi
exec "$python" -B "$root/safe_install.py" "$@"
