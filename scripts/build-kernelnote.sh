#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/scripts/build-kernelnote-core.sh"
# The generated script must remain in scripts/. build-kernelnote-core.sh derives
# the repository root from BASH_SOURCE[0]/..; placing it in /tmp resolves ROOT=/
# and makes the build try to create /work, /logs and /artifacts.
GENERATED="$ROOT/scripts/.build-kernelnote-integrated-$$.sh"
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
        raise SystemExit(
            f"expected exactly one injection anchor, found {count}: {old[:100]!r}"
        )
    source = source.replace(old, new, 1)


replace_once(
    'MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"\n',
    '''MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"

# ZRAM Immediate Recompression: native Linux 7.1 patch.
ZRAM_IR_REPO="https://github.com/firelzrd/zram-ir.git"
ZRAM_IR_COMMIT="e348391dcf54bc42904f227f5ee83d2790f28f52"
ZRAM_IR_PATCH_PATH="patches/0001-linux7.1-rc1-zram-ir-1.2.patch"
ZRAM_IR_DIR="$WORKDIR/zram-ir"
ZRAM_IR_PATCH="$PATCHDIR/0004-zram-ir-1.2-linux7.1.patch"

# POC Selector: use the native Linux 7.1 stable patch rather than an older port.
POC_REPO="https://github.com/firelzrd/poc-selector.git"
POC_COMMIT="f2e9d6027ec8a9167365acd828016da9c8bd28e1"
POC_PATCH_PATH="patches/stable/0001-7.1-rc1-poc-selector-v2.6.2r2.patch"
POC_DIR="$WORKDIR/poc-selector"
POC_PATCH="$PATCHDIR/0005-poc-selector-v2.6.2r2-linux7.1.patch"

# NAP 0.5.0 has no native Linux 7.1 patch. Pin the stable 6.18.3 source and
# apply it as a controlled port; the build reports every reject if APIs moved.
NAP_REPO="https://github.com/firelzrd/nap.git"
NAP_COMMIT="b4ca3378854a067bb639c60d9d8175ecc0a804bf"
NAP_PATCH_PATH="patches/stable/0001-6.18.3-nap-v0.5.0.patch"
NAP_DIR="$WORKDIR/nap"
NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"
'''
)

replace_once(
    '''KERNEL_DEFAULT_CMDLINE=(
  "mitigations=off"
  "nowatchdog"
  "intel_pstate=passive"
  "amd_pstate=passive"
)
''',
    '''KERNEL_DEFAULT_CMDLINE=(
  "mitigations=off"
  "nowatchdog"
  "intel_pstate=passive"
  "amd_pstate=passive"
  "cpuidle.governor=nap"
)
'''
)

replace_once(
    'normalize_changed_whitespace() {\n',
    r'''fetch_pinned_patch() {
  local label="$1" repo="$2" commit="$3" path="$4"
  local checkout="$5" output="$6" subject="$7" log_prefix="$8"

  echo "==> Fetching pinned $label source locally"
  rm -rf "$checkout"
  git init --quiet "$checkout"
  git -C "$checkout" remote add origin "$repo"
  git -C "$checkout" config remote.origin.promisor true
  git -C "$checkout" config remote.origin.partialclonefilter blob:none
  git -C "$checkout" fetch --no-tags --depth=1 --filter=blob:none origin "$commit" \
    2>&1 | tee "$LOGDIR/${log_prefix}-fetch.log"

  git -C "$checkout" show "FETCH_HEAD:$path" > "$output"
  test -s "$output"
  grep -Fq "$subject" "$output"

  {
    echo "Component: $label"
    echo "Repository: $repo"
    echo "Commit: $commit"
    echo "Path: $path"
    echo "SHA256: $(sha256sum "$output" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout"
  } | tee "$LOGDIR/${log_prefix}-provenance.txt"
}

fetch_zram_ir_patch() {
  fetch_pinned_patch \
    "ZRAM-IR 1.2 for Linux 7.1" \
    "$ZRAM_IR_REPO" "$ZRAM_IR_COMMIT" "$ZRAM_IR_PATCH_PATH" \
    "$ZRAM_IR_DIR" "$ZRAM_IR_PATCH" \
    'Subject: [PATCH] linux7.1-rc1-zram-ir-1.2' \
    "04-zram-ir"
}

fetch_poc_patch() {
  fetch_pinned_patch \
    "POC Selector 2.6.2r2 for Linux 7.1" \
    "$POC_REPO" "$POC_COMMIT" "$POC_PATCH_PATH" \
    "$POC_DIR" "$POC_PATCH" \
    'Subject: [PATCH] 7.1-rc1-poc-selector-v2.6.2r2' \
    "05-poc-selector"
}

fetch_nap_patch() {
  fetch_pinned_patch \
    "NAP 0.5.0 stable port source" \
    "$NAP_REPO" "$NAP_COMMIT" "$NAP_PATCH_PATH" \
    "$NAP_DIR" "$NAP_PATCH" \
    'Subject: [PATCH] 6.18.3-nap-v0.5.0' \
    "06-nap"
}

report_patch_rejects() {
  local component="$1" output="$2"
  {
    echo "==> Unresolved $component port rejects"
    find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
    echo
    while IFS= read -r reject; do
      echo "### ${reject#$KERNELDIR/}"
      cat "$reject"
    done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
  } | tee "$output"
}

normalize_changed_whitespace() {
'''
)

replace_once(
    'apply_bore_patch() {\n',
    r'''apply_zram_ir_patch() {
  local file="$1" status=0

  echo "==> Applying ZRAM Immediate Recompression 1.2 for Linux 7.1"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/04-zram-ir.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/04-zram-ir.apply.log"
  else
    cat "$LOGDIR/04-zram-ir.dry-run.log"
    echo "==> Retrying ZRAM-IR with maximum safe patch fuzz"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/04-zram-ir.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/04-zram-ir.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      report_patch_rejects "ZRAM-IR" "$LOGDIR/04-zram-ir-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check -- drivers/block/zram/zram_drv.c \
    | tee "$LOGDIR/04-zram-ir-diff-check.log"
  grep -Fq '#define ZRAM_IR_VERSION "1.2"' drivers/block/zram/zram_drv.c
  grep -Fq 'zram_recomp_immediate' drivers/block/zram/zram_drv.c
  grep -Fq 'register_sysctl("vm", zram_sysctl_table)' drivers/block/zram/zram_drv.c
  echo "==> ZRAM-IR 1.2 patch applied successfully"
}

apply_poc_patch() {
  local file="$1" status=0

  echo "==> Applying native Linux 7.1 POC Selector 2.6.2r2"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/05-poc-selector.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/05-poc-selector.apply.log"
  else
    cat "$LOGDIR/05-poc-selector.dry-run.log"
    echo "==> Porting POC Selector across Liquorix/BORE offsets with fuzz <= 3"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/05-poc-selector.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/05-poc-selector.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      report_patch_rejects "POC Selector" "$LOGDIR/05-poc-selector-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check -- include/linux/sched/topology.h init/Kconfig kernel/sched \
    | tee "$LOGDIR/05-poc-selector-diff-check.log"
  test -s kernel/sched/poc_selector.c
  grep -Fq 'config SCHED_POC_SELECTOR' init/Kconfig
  grep -Fq 'poc_selector_active' kernel/sched/poc_selector.c
  echo "==> POC Selector 2.6.2r2 applied successfully"
}

apply_nap_patch() {
  local file="$1" status=0

  echo "==> Porting NAP 0.5.0 from Linux 6.18.3 to Liquorix Linux 7.1"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/06-nap.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/06-nap.apply.log"
  else
    cat "$LOGDIR/06-nap.dry-run.log"
    echo "==> Retrying NAP port with maximum safe patch fuzz"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/06-nap.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/06-nap.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      report_patch_rejects "NAP" "$LOGDIR/06-nap-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check -- drivers/cpuidle \
    | tee "$LOGDIR/06-nap-diff-check.log"
  test -s drivers/cpuidle/governors/nap/nap.c
  grep -Fq 'config CPU_IDLE_GOV_NAP' drivers/cpuidle/Kconfig
  grep -Fq '#define CPUIDLE_NAP_VERSION  "0.5.0"' \
    drivers/cpuidle/governors/nap/nap.c
  echo "==> NAP 0.5.0 Linux 7.1 port applied successfully"
}

apply_bore_patch() {
'''
)

replace_once(
    'fetch_marie_testing_patch\n',
    '''fetch_marie_testing_patch
fetch_zram_ir_patch
fetch_poc_patch
fetch_nap_patch
'''
)

replace_once(
    '''apply_marie_testing_patch "$MARIE_PATCH"
apply_bore_patch "$BORE_PATCH"
apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"
apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"
''',
    '''apply_marie_testing_patch "$MARIE_PATCH"
apply_bore_patch "$BORE_PATCH"
apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"
apply_poc_patch "$POC_PATCH"
apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"
apply_zram_ir_patch "$ZRAM_IR_PATCH"
apply_nap_patch "$NAP_PATCH"
'''
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
scripts/config --enable SCHED_POC_SELECTOR
scripts/config --enable CPU_IDLE_GOV_NAP
'''
)

replace_once(
    '''# PR validation exercises the complete built-in kernel and ThinLTO link, but
# omits DWARF/BTF generation and loadable modules. Full package mode keeps the
# production configuration and builds every configured module.
if [[ "$MODE" == "validate" ]]; then
  scripts/config --disable DEBUG_INFO
  scripts/config --enable DEBUG_INFO_NONE
  scripts/config --disable DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT
  scripts/config --disable DEBUG_INFO_DWARF4
  scripts/config --disable DEBUG_INFO_DWARF5
  scripts/config --disable DEBUG_INFO_BTF
fi
''',
    '''# DWARF/BTF generation dominates hosted-runner time and creates an enormous
# debug package. Disable it in both validation and package modes; this does not
# remove runtime symbols, modules, headers, ThinLTO, or the installable image.
scripts/config --disable DEBUG_INFO
scripts/config --enable DEBUG_INFO_NONE
scripts/config --disable DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT
scripts/config --disable DEBUG_INFO_DWARF4
scripts/config --disable DEBUG_INFO_DWARF5
scripts/config --disable DEBUG_INFO_BTF
scripts/config --disable GDB_SCRIPTS
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
assert_config "CONFIG_SCHED_POC_SELECTOR=y"
assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"
'''
)

replace_once(
    'assert_cmdline_token "nowatchdog"\n',
    '''assert_cmdline_token "nowatchdog"
assert_cmdline_token "intel_pstate=passive"
assert_cmdline_token "amd_pstate=passive"
assert_cmdline_token "cpuidle.governor=nap"
'''
)

replace_once(
    '''if [[ "$MODE" == "validate" ]]; then
  assert_config "CONFIG_DEBUG_INFO_NONE=y"
  assert_disabled_or_absent DEBUG_INFO
  assert_disabled_or_absent DEBUG_INFO_BTF
fi
''',
    '''assert_config "CONFIG_DEBUG_INFO_NONE=y"
assert_disabled_or_absent DEBUG_INFO
assert_disabled_or_absent DEBUG_INFO_BTF
assert_disabled_or_absent GDB_SCRIPTS
'''
)

replace_once(
    'scripts/config --set-str LOCALVERSION "-kernelnote-lqx-marie-bore-adios-thinlto"\n',
    'scripts/config --set-str LOCALVERSION "-kn-marie-bore-poc-nap-rfx-adios-zir-lto"\n'
)

replace_once(
    '"${MAKE[@]}" -s kernelrelease | tee "$LOGDIR/kernelrelease.txt"\n',
    '''kernel_release="$("${MAKE[@]}" -s kernelrelease)"
printf '%s\n' "$kernel_release" | tee "$LOGDIR/kernelrelease.txt"
if ((${#kernel_release} > 64)); then
  echo "Kernel release exceeds the 64-character UTS_RELEASE limit: ${#kernel_release}" >&2
  exit 1
fi
'''
)

output.write_text(source, encoding="utf-8")
PY

chmod 0755 "$GENERATED"
bash -n "$GENERATED"
"$GENERATED" "$@"
