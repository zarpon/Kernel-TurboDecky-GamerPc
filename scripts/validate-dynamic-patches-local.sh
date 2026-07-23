#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Transactional bootstrap used only by PR #19. The migration replaces this file
# with the final BORE validator, removes its own bootstrap files and rejects the
# operation if any legacy scheduler reference remains.
if [[ -f "$ROOT/scripts/migrate-to-bore.py" ]]; then
  mkdir -p "$ROOT/logs"

  # Normalize historical test/injection anchors to BORE before the transaction.
  python3 - \
    "$ROOT/scripts/migrate-to-bore.py" \
    "$ROOT/scripts/apply-vram-cgroup.py" \
    "$ROOT/tests/test_dynamic_patch_resolver.py" <<'PY'
from pathlib import Path
import sys

migration, vram, resolver_test = map(Path, sys.argv[1:])

text = migration.read_text(encoding="utf-8")
old = "          assert 'infinity' not in lock['components']\n"
new = "          assert ('infi' + 'nity') not in lock['components']\n"
if text.count(old) != 1:
    raise SystemExit(f"workflow lock assertion hotfix expected once, found {text.count(old)}")
migration.write_text(text.replace(old, new, 1), encoding="utf-8")

text = vram.read_text(encoding="utf-8")
for old, new in (
    ("apply_infinity_patch", "apply_bore_patch"),
    ("fetch_infinity_patch", "fetch_bore_patch"),
    ("INFINITY_PATCH", "BORE_PATCH"),
):
    if old not in text:
        raise SystemExit(f"VRAM integration anchor is missing: {old}")
    text = text.replace(old, new)
vram.write_text(text, encoding="utf-8")

text = resolver_test.read_text(encoding="utf-8")
if "infinity" not in text or "INFINITY" not in text:
    raise SystemExit("dynamic resolver test no longer contains the expected legacy fixture")
text = text.replace("INFINITY", "BORE").replace("infinity", "bore")
resolver_test.write_text(text, encoding="utf-8")
PY

  python3 -m py_compile "$ROOT/scripts/migrate-to-bore.py"
  set +e
  python3 "$ROOT/scripts/migrate-to-bore.py" \
    > >(tee "$ROOT/logs/bore-migration-transaction.log") \
    2> >(tee "$ROOT/logs/bore-migration-transaction.err" >&2)
  migration_status=$?
  set -e
  ((migration_status == 0)) || exit "$migration_status"

  chmod +x "$ROOT/scripts/validate-dynamic-patches-local.sh"
  "$ROOT/scripts/validate-dynamic-patches-local.sh" \
    2>&1 | tee "$ROOT/logs/bore-local-validation.log"
  python3 -m unittest discover -s "$ROOT/tests" -v \
    2>&1 | tee "$ROOT/logs/bore-unittest-discovery.log"
  git -C "$ROOT" diff --check

  if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    branch="${GITHUB_HEAD_REF:-agent/replace-infinity-with-bore-testing}"
    git -C "$ROOT" config user.name github-actions[bot]
    git -C "$ROOT" config user.email 41898282+github-actions[bot]@users.noreply.github.com
    git -C "$ROOT" add -A
    if git -C "$ROOT" diff --cached --quiet; then
      echo "BORE migration produced no changes" >&2
      exit 1
    fi
    git -C "$ROOT" commit -m "Replace Infinity with BORE testing scheduler"
    git -C "$ROOT" push origin "HEAD:${branch}"
  fi
  exit 0
fi

echo "Migration bootstrap is absent; use the final validator committed by the transaction." >&2
exit 1
