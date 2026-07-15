#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/scripts/build-kernelnote-core.sh"
# The generated script must remain in scripts/. build-kernelnote-core.sh derives
# the repository root from BASH_SOURCE[0]/..; placing it in /tmp incorrectly
# resolves ROOT=/ and makes the build try to create /work, /logs and /artifacts.
GENERATED="$ROOT/scripts/.build-kernelnote-zram-ir-$$.sh"
trap 'rm -f "$GENERATED"' EXIT

python3 - "$CORE" "$GENERATED" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
output = Path(sys.argv[2])

def replace_once(old: str, new: str) -> None:
    global source
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one injection anchor, found {count}: {old[:80]!r}")
    source = source.replace(old, new, 1)

replace_once(
    'MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"\n',
    '''MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"

# ZRAM Immediate Recompression is acquired from a pinned local partial checkout.
ZRAM_IR_REPO="https://github.com/firelzrd/zram-ir.git"
ZRAM_IR_COMMIT="e348391dcf54bc42904f227f5ee83d2790f28f52"
ZRAM_IR_PATCH_PATH="patches/0001-linux7.1-rc1-zram-ir-1.2.patch"
ZRAM_IR_DIR="$WORKDIR/zram-ir"
ZRAM_IR_PATCH="$PATCHDIR/0004-zram-ir-1.2-linux7.1.patch"
'''
)

replace_once(
    'normalize_changed_whitespace() {\n',
    '''fetch_zram_ir_patch() {
  echo "==> Fetching pinned ZRAM-IR 1.2 source locally"
  rm -rf "$ZRAM_IR_DIR"
  git init --quiet "$ZRAM_IR_DIR"
  git -C "$ZRAM_IR_DIR" remote add origin "$ZRAM_IR_REPO"
  git -C "$ZRAM_IR_DIR" config remote.origin.promisor true
  git -C "$ZRAM_IR_DIR" config remote.origin.partialclonefilter blob:none
  git -C "$ZRAM_IR_DIR" fetch --no-tags --depth=1 --filter=blob:none origin "$ZRAM_IR_COMMIT" \\
    2>&1 | tee "$LOGDIR/04-zram-ir-fetch.log"

  git -C "$ZRAM_IR_DIR" show "FETCH_HEAD:$ZRAM_IR_PATCH_PATH" > "$ZRAM_IR_PATCH"
  test -s "$ZRAM_IR_PATCH"
  grep -Fq 'Subject: [PATCH] linux7.1-rc1-zram-ir-1.2' "$ZRAM_IR_PATCH"

  {
    echo "Repository: firelzrd/zram-ir"
    echo "Commit: $ZRAM_IR_COMMIT"
    echo "Path: $ZRAM_IR_PATCH_PATH"
    echo "SHA256: $(sha256sum "$ZRAM_IR_PATCH" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout"
  } | tee "$LOGDIR/04-zram-ir-provenance.txt"
}

normalize_changed_whitespace() {
'''
)

replace_once(
    'apply_bore_patch() {\n',
    '''apply_zram_ir_patch() {
  local file="$1" status=0

  echo "==> Applying ZRAM Immediate Recompression 1.2 for Linux 7.1"
  if patch --batch --forward --strip=1 --dry-run < "$file" \\
      > "$LOGDIR/04-zram-ir.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \\
      | tee "$LOGDIR/04-zram-ir.apply.log"
  else
    cat "$LOGDIR/04-zram-ir.dry-run.log"
    echo "==> Retrying ZRAM-IR with maximum safe patch fuzz"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \\
      > "$LOGDIR/04-zram-ir.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/04-zram-ir.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      {
        echo "==> Unresolved ZRAM-IR port rejects"
        find "$KERNELDIR" -name '*.rej' -printf '%P\\n' | sort
        echo
        while IFS= read -r reject; do
          echo "### ${reject#$KERNELDIR/}"
          cat "$reject"
        done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
      } | tee "$LOGDIR/04-zram-ir-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \\( -name '*.rej' -o -name '*.orig' \\) -delete
  git diff --check -- drivers/block/zram/zram_drv.c \\
    | tee "$LOGDIR/04-zram-ir-diff-check.log"
  grep -Fq '#define ZRAM_IR_VERSION "1.2"' drivers/block/zram/zram_drv.c
  grep -Fq 'zram_recomp_immediate' drivers/block/zram/zram_drv.c
  grep -Fq 'register_sysctl("vm", zram_sysctl_table)' drivers/block/zram/zram_drv.c
  echo "==> ZRAM-IR 1.2 patch applied successfully"
}

apply_bore_patch() {
'''
)

replace_once(
    'fetch_marie_testing_patch\n',
    'fetch_marie_testing_patch\nfetch_zram_ir_patch\n'
)

replace_once(
    'apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"\n',
    'apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"\napply_zram_ir_patch "$ZRAM_IR_PATCH"\n'
)

replace_once(
    'scripts/config --module BLK_DEV_ZRAM\n',
    '''scripts/config --module ZRAM
scripts/config --enable ZRAM_MULTI_COMP
scripts/config --enable ZRAM_BACKEND_LZ4
scripts/config --enable ZRAM_BACKEND_ZSTD
scripts/config --disable ZRAM_DEF_COMP_LZORLE
scripts/config --disable ZRAM_DEF_COMP_LZO
scripts/config --disable ZRAM_DEF_COMP_LZ4HC
scripts/config --disable ZRAM_DEF_COMP_ZSTD
scripts/config --disable ZRAM_DEF_COMP_DEFLATE
scripts/config --disable ZRAM_DEF_COMP_842
scripts/config --enable ZRAM_DEF_COMP_LZ4
'''
)

replace_once(
    'assert_config "CONFIG_MQ_IOSCHED_DEFAULT_ADIOS=y"\n',
    '''assert_config "CONFIG_MQ_IOSCHED_DEFAULT_ADIOS=y"
assert_config "CONFIG_ZRAM=m"
assert_config "CONFIG_ZRAM_MULTI_COMP=y"
assert_config "CONFIG_ZRAM_BACKEND_LZ4=y"
assert_config "CONFIG_ZRAM_BACKEND_ZSTD=y"
assert_config "CONFIG_ZRAM_DEF_COMP_LZ4=y"
'''
)

output.write_text(source, encoding="utf-8")
PY

chmod 0755 "$GENERATED"
bash -n "$GENERATED"
"$GENERATED" "$@"
