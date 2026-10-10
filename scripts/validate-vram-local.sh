#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m py_compile \
  "$ROOT/scripts/apply-vram-cgroup.py" \
  "$ROOT/scripts/apply-zarpon-generic-name.py"
bash -n "$ROOT/scripts/build-vram-package.sh"

! grep -Fq 'fetch_vram_patch' "$ROOT/scripts/apply-vram-cgroup.py"
grep -Fq 'scripts/config --enable CGROUP_DMEM' \
  "$ROOT/scripts/apply-vram-cgroup.py"
grep -Fq '95162bdd9be9c4bd89d65cb558acb858c35f8bf6' \
  "$ROOT/scripts/build-vram-package.sh"
! grep -Fq -- '--fuzz' "$ROOT/scripts/apply-vram-cgroup.py"

echo "VRAM integration static validation passed"
