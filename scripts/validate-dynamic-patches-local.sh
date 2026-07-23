#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Transactional bootstrap used only by PR #19. The migration replaces this file
# with the final BORE validator, removes its own bootstrap files and rejects the
# operation if any legacy scheduler reference remains.
if [[ -f "$ROOT/scripts/migrate-to-bore.py" ]]; then
  python3 -m py_compile "$ROOT/scripts/migrate-to-bore.py"
  python3 "$ROOT/scripts/migrate-to-bore.py"

  chmod +x "$ROOT/scripts/validate-dynamic-patches-local.sh"
  "$ROOT/scripts/validate-dynamic-patches-local.sh"
  python3 -m unittest discover -s "$ROOT/tests" -v
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
