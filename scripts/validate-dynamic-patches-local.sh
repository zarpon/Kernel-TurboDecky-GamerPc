#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m py_compile \
  "$ROOT/scripts/resolve-patch-sources.py" \
  "$ROOT/scripts/apply-dynamic-patch-sources.py" \
  "$ROOT/scripts/apply-zarpon-generic-name.py"
python3 -m json.tool "$ROOT/config/patch-sources.json" >/dev/null
python3 -m unittest -v "$ROOT/tests/test_dynamic_patch_resolver.py"

grep -Fq '"infinity"' "$ROOT/config/patch-sources.json"
grep -Fq '"vram"' "$ROOT/config/patch-sources.json"
grep -Fq 'fallback_refs' "$ROOT/config/patch-sources.json"
grep -Fq 'patch-lock.json' "$ROOT/scripts/apply-dynamic-patch-sources.py"
grep -Fq 'KERNEL_VERSION' "$ROOT/scripts/apply-zarpon-generic-name.py"

echo "Dynamic patch source validation passed"
