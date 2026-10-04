#!/usr/bin/env bash
# Native entry point; transaction and logging behavior live in safe_install.py.
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="${REVAYAT_PYTHON:-}"
if [ -z "$python" ]; then
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            python="$candidate"
            break
        fi
    done
fi
if [ -z "$python" ] || ! "$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    printf '%s [ERROR] [installer] Python 3.10+ is required; set REVAYAT_PYTHON to its executable.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >&2
    exit 1
fi
exec "$python" -B "$root/safe_install.py" "$@"
