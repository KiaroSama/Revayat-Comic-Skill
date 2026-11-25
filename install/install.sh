#!/usr/bin/env bash
# Native entry point invoking the pure-Rust revayat-comic CLI binary (no Python required).
set -euo pipefail
root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
binary="${REVAYAT_BIN:-}"
if [ -z "$binary" ]; then
    for candidate in "$root/bin/revayat-comic" "$root/target/release/revayat-comic" "$(command -v revayat-comic 2>/dev/null || true)"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            binary="$candidate"
            break
        fi
    done
fi
if [ -z "$binary" ] || [ ! -x "$binary" ]; then
    printf '%s [ERROR] [installer] revayat-comic binary not found; build with "cargo build --release --locked -p revayat-comic-cli" or set REVAYAT_BIN.\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >&2
    exit 1
fi
exec "$binary" install --repo "$root" "$@"
