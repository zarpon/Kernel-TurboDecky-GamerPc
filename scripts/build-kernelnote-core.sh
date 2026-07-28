#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-validate}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$ROOT/work"
LOGDIR="$ROOT/logs"
ARTIFACTS="$ROOT/artifacts"
PATCHDIR="$WORKDIR/patches"
KERNELDIR="$WORKDIR/linux"
MARIEDIR="$WORKDIR/lru_marie"
JOBS="${JOBS:-$(nproc --all)}"
MAKE=(make LLVM=1 LLVM_IAS=1)

KERNEL_TAG="v7.1.4"
KERNEL_REPO="https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
LIQUORIX_CONFIG_URL="https://raw.githubusercontent.com/damentz/liquorix-package/56f0e85662990ee20b4ea10465a41a23b65ace2c/linux-liquorix/debian/config/kernelarch-x86/config-arch-64"
ADIOS_URL="https://raw.githubusercontent.com/firelzrd/adios/08bf078aac99075a0bef73c2b2497574a82e4c41/patches/stable/0001-linux6.19.3-ADIOS-3.2.0.patch"

# Bootstrap anchors for the generated build only. The resolver obtains current
# upstream BORE and sched_ext bytes, then finalize-bore-stable-port.py replaces
# every version, digest and port path from that exact lock before this script is
# executed. These template values must never be treated as an active pin.
BORE_REPO="https://github.com/firelzrd/bore-scheduler.git"
BORE_BRANCH="main"
BORE_COMMIT="16bf5baebbb42cdba393c501ba9c2af5f84e4749"
BORE_PATCH_PATH="patches/testing/0001-linux7.1-rc1-bore-6.8.0-rc1.patch"
BORE_DIR="$WORKDIR/bore-scheduler"
BORE_UPSTREAM_PATCH="$PATCHDIR/0001-bore-upstream.patch"
BORE_PATCH="$ROOT/patches/bore/7.1.4-bore-6.8.0-rc1.patch"
BORE_PORT_VERSION="6.8.0-rc1"
BORE_PORT_UPSTREAM_SHA256="87b9b6f5bedc05db2fb59e921ca7cd172a2a68c1267834d5c5c771cc0f48fd36"
BORE_SCHED_EXT_REPO="https://github.com/firelzrd/bore-scheduler.git"
BORE_SCHED_EXT_COMMIT="16bf5baebbb42cdba393c501ba9c2af5f84e4749"
BORE_SCHED_EXT_PATCH_PATH="patches/additions/0002-sched-ext-coexistence-fix.patch"
BORE_SCHED_EXT_DIR="$WORKDIR/bore-scheduler-sched-ext"
BORE_SCHED_EXT_UPSTREAM_PATCH="$PATCHDIR/0002-bore-sched-ext-upstream.patch"
BORE_SCHED_EXT_PATCH="$ROOT/patches/bore/7.1.4-sched-ext-coexistence-fix.patch"
BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="cdf138cdb94fcb4e2988bd7d2873a51522fdb7212ec314fde202facaf8210b5c"

# Marie is fetched as a pinned local Git checkout rather than through a raw
# patch URL. Only the exact patch blob is materialized in the workspace.
MARIE_REPO="https://github.com/firelzrd/lru_marie.git"
MARIE_COMMIT="27617bc12be6646890b3df406b97172ed6f7364e"
MARIE_PATCH_PATH="patches/testing/0001-linux7.1-rc5-lru_marie-0.9.1.patch"
MARIE_PATCH="$PATCHDIR/02-lru-marie.patch"
PATCH_MARIE_VERSION="${PATCH_MARIE_VERSION:-0.9.1}"
MARIE_FALLBACK_PATCH="$ROOT/patches/fallback/lru_marie.patch"
MARIE_FALLBACK_METADATA="$ROOT/patches/fallback/lru_marie.json"

# Keep the existing Liquorix built-in arguments and append these canonical
# kernel parameters. CMDLINE_OVERRIDE stays disabled so bootloader parameters
# such as root=, resume= and console= are preserved.
KERNEL_DEFAULT_CMDLINE=(
  "mitigations=off"
  "nowatchdog"
  "intel_pstate=passive"
  "amd_pstate=passive"
)

case "$MODE" in
  validate|package) ;;
  *) echo "Usage: $0 [validate|package]" >&2; exit 2 ;;
esac

rm -rf "$WORKDIR" "$LOGDIR" "$ARTIFACTS"
mkdir -p "$PATCHDIR" "$LOGDIR" "$ARTIFACTS"
exec > >(tee "$LOGDIR/build.log") 2>&1

trap 'status=$?; echo "Build failed with status $status at line $LINENO"; find "$KERNELDIR" \( -name "*.rej" -o -name "*.orig" \) 2>/dev/null | sort || true; exit $status' ERR

download() {
  local url="$1" output="$2"
  curl --fail --location --retry 4 --retry-all-errors --retry-delay 3 \
    --connect-timeout 30 --max-time 600 "$url" -o "$output"
  test -s "$output"
  sha256sum "$output" | tee -a "$LOGDIR/downloads.sha256"
}

fetch_marie_testing_patch() {
  local acquisition="pinned local partial Git checkout; no raw patch URL"
  echo "==> Fetching pinned Marie LRU $PATCH_MARIE_VERSION testing source locally"
  rm -rf "$MARIEDIR"
  git init --quiet "$MARIEDIR"
  git -C "$MARIEDIR" remote add origin "$MARIE_REPO"
  git -C "$MARIEDIR" config remote.origin.promisor true
  git -C "$MARIEDIR" config remote.origin.partialclonefilter blob:none

  if git -C "$MARIEDIR" fetch --no-tags --depth=1 --filter=blob:none origin "$MARIE_COMMIT" \
      2>&1 | tee "$LOGDIR/02-lru-marie-fetch.log" && \
      git -C "$MARIEDIR" show "FETCH_HEAD:$MARIE_PATCH_PATH" > "$MARIE_PATCH"; then
    test -s "$MARIE_PATCH"
  else
    rm -f "$MARIE_PATCH"
    echo "==> Marie upstream source unavailable; using maintained local fallback"
    python3 "$ROOT/scripts/validate-marie-fallback.py" \
      --patch "$MARIE_FALLBACK_PATCH" \
      --metadata "$MARIE_FALLBACK_METADATA"
    PATCH_MARIE_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project_version"])' "$MARIE_FALLBACK_METADATA")"
    MARIE_COMMIT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$MARIE_FALLBACK_METADATA")"
    MARIE_PATCH_PATH="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["selected_path"])' "$MARIE_FALLBACK_METADATA")"
    cp "$MARIE_FALLBACK_PATCH" "$MARIE_PATCH"
    acquisition="maintained local fallback"
  fi

  test -s "$MARIE_PATCH"
  grep -Fq 'lru_marie' "$MARIE_PATCH"
  grep -Fq 'LRU_MARIE' "$MARIE_PATCH"

  {
    echo "Marie source policy: testing-compatible"
    echo "Repository: firelzrd/lru_marie"
    echo "Commit: $MARIE_COMMIT"
    echo "Version: $PATCH_MARIE_VERSION"
    echo "Path: $MARIE_PATCH_PATH"
    echo "SHA256: $(sha256sum "$MARIE_PATCH" | awk '{print $1}')"
    echo "Acquisition: $acquisition"
  } | tee "$LOGDIR/02-lru-marie-provenance.txt"
}

fetch_bore_source() {
  local upstream_sha256

  echo "==> Fetching the pinned upstream BORE $BORE_PORT_VERSION source locally"
  rm -rf "$BORE_DIR"
  git init --quiet "$BORE_DIR"
  git -C "$BORE_DIR" remote add origin "$BORE_REPO"
  git -C "$BORE_DIR" config remote.origin.promisor true
  git -C "$BORE_DIR" config remote.origin.partialclonefilter blob:none
  git -C "$BORE_DIR" fetch --no-tags --depth=1 --filter=blob:none origin "$BORE_COMMIT" \
    2>&1 | tee "$LOGDIR/01-bore-fetch.log"

  git -C "$BORE_DIR" show "FETCH_HEAD:$BORE_PATCH_PATH" > "$BORE_UPSTREAM_PATCH"
  test -s "$BORE_UPSTREAM_PATCH"
  grep -Fq 'diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c' "$BORE_UPSTREAM_PATCH"
  grep -Fq 'SCHED_BORE_VERSION  "6.8.0-rc1"' "$BORE_UPSTREAM_PATCH"
  grep -Fq 'sched_bore' "$BORE_UPSTREAM_PATCH"
  upstream_sha256="$(sha256sum "$BORE_UPSTREAM_PATCH" | awk '{print $1}')"
  if [[ "$upstream_sha256" != "$BORE_PORT_UPSTREAM_SHA256" ]]; then
    echo "BORE upstream SHA-256 $upstream_sha256 no longer matches the reviewed $BORE_PORT_VERSION port ($BORE_PORT_UPSTREAM_SHA256)" >&2
    return 1
  fi

  test -s "$BORE_PATCH"
  grep -Fq 'sched: port BORE 6.8.0-rc1 to Linux 7.1.4' "$BORE_PATCH"
  grep -Fq 'diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c' "$BORE_PATCH"
  grep -Fq 'SCHED_BORE_VERSION' "$BORE_PATCH"

  {
    echo "Component: BORE scheduler $BORE_PORT_VERSION"
    echo "Repository: $BORE_REPO"
    echo "Branch: $BORE_BRANCH"
    echo "Commit: $BORE_COMMIT"
    echo "Upstream path: $BORE_PATCH_PATH"
    echo "Upstream SHA256: $upstream_sha256"
    echo "Reviewed port upstream SHA256: $BORE_PORT_UPSTREAM_SHA256"
    echo "Linux port: ${BORE_PATCH#$ROOT/}"
    echo "Linux port SHA256: $(sha256sum "$BORE_PATCH" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout plus reviewed local port"
  } | tee "$LOGDIR/01-bore-provenance.txt"
}

fetch_bore_sched_ext_source() {
  local upstream_sha256

  echo "==> Fetching the pinned upstream BORE sched_ext coexistence fix"
  rm -rf "$BORE_SCHED_EXT_DIR"
  git init --quiet "$BORE_SCHED_EXT_DIR"
  git -C "$BORE_SCHED_EXT_DIR" remote add origin "$BORE_SCHED_EXT_REPO"
  git -C "$BORE_SCHED_EXT_DIR" config remote.origin.promisor true
  git -C "$BORE_SCHED_EXT_DIR" config remote.origin.partialclonefilter blob:none
  git -C "$BORE_SCHED_EXT_DIR" fetch --no-tags --depth=1 --filter=blob:none origin "$BORE_SCHED_EXT_COMMIT" 2>&1 | tee "$LOGDIR/01-bore-sched-ext-fetch.log"

  git -C "$BORE_SCHED_EXT_DIR" show "FETCH_HEAD:$BORE_SCHED_EXT_PATCH_PATH" > "$BORE_SCHED_EXT_UPSTREAM_PATCH"
  test -s "$BORE_SCHED_EXT_UPSTREAM_PATCH"
  grep -Fq 'Subject: [PATCH] sched-ext-coexistence-fix' "$BORE_SCHED_EXT_UPSTREAM_PATCH"
  grep -Fq 'void reweight_task(struct task_struct *p, int prio)' "$BORE_SCHED_EXT_UPSTREAM_PATCH"
  upstream_sha256="$(sha256sum "$BORE_SCHED_EXT_UPSTREAM_PATCH" | awk '{print $1}')"
  if [[ "$upstream_sha256" != "$BORE_SCHED_EXT_PORT_UPSTREAM_SHA256" ]]; then
    echo "BORE sched_ext upstream SHA-256 $upstream_sha256 no longer matches the reviewed port ($BORE_SCHED_EXT_PORT_UPSTREAM_SHA256)" >&2
    return 1
  fi

  test -s "$BORE_SCHED_EXT_PATCH"
  grep -Fq 'sched: port 0002 sched-ext coexistence fix to Linux 7.1.4' "$BORE_SCHED_EXT_PATCH"
  grep -Fq 'extern void reweight_task(struct task_struct *p, int prio);' "$BORE_SCHED_EXT_PATCH"

  {
    echo "Component: BORE sched_ext coexistence fix"
    echo "Repository: $BORE_SCHED_EXT_REPO"
    echo "Commit: $BORE_SCHED_EXT_COMMIT"
    echo "Upstream path: $BORE_SCHED_EXT_PATCH_PATH"
    echo "Upstream SHA256: $upstream_sha256"
    echo "Reviewed port upstream SHA256: $BORE_SCHED_EXT_PORT_UPSTREAM_SHA256"
    echo "Linux port: ${BORE_SCHED_EXT_PATCH#$ROOT/}"
    echo "Linux port SHA256: $(sha256sum "$BORE_SCHED_EXT_PATCH" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout plus reviewed local port"
  } | tee "$LOGDIR/01-bore-sched-ext-provenance.txt"
}

normalize_changed_whitespace() {
  mapfile -d '' -t changed_files < <(git diff --name-only --diff-filter=ACM -z)
  ((${#changed_files[@]})) || return 0

  python3 - "${changed_files[@]}" <<'PY'
from pathlib import Path
import re
import sys

for name in sys.argv[1:]:
    path = Path(name)
    try:
        raw = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        continue

    output = []
    for line in raw.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        body = body.rstrip(" \t")
        match = re.match(r"^[ \t]+", body)
        if match:
            prefix = match.group(0)
            while " \t" in prefix:
                prefix = prefix.replace(" \t", "\t")
            body = prefix + body[match.end():]
        output.append(body + ending)

    path.write_text("".join(output), encoding="utf-8")
PY
}

apply_marie_testing_patch() {
  local file="$1" status=0

  echo "==> Applying local Marie LRU $PATCH_MARIE_VERSION testing patch for Linux 7.1"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/02-lru-marie.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/02-lru-marie.apply.log"
  else
    cat "$LOGDIR/02-lru-marie.dry-run.log"
    echo "==> Retrying Marie with maximum safe patch fuzz"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/02-lru-marie.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/02-lru-marie.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      {
        echo "==> Unresolved Marie port rejects"
        find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
        echo
        for reject in $(find "$KERNELDIR" -name '*.rej' -type f | sort); do
          echo "### ${reject#$KERNELDIR/}"
          cat "$reject"
        done
      } | tee "$LOGDIR/02-lru-marie-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete

  if ! git diff --check > "$LOGDIR/02-lru-marie-diff-check.log" 2>&1; then
    cat "$LOGDIR/02-lru-marie-diff-check.log"
    echo "==> Normalizing whitespace introduced by patch offsets"
    normalize_changed_whitespace
    git diff --check | tee "$LOGDIR/02-lru-marie-diff-check-after-fix.log"
  fi

  grep -Fq "$PATCH_MARIE_VERSION" mm/lru_marie/version.h
  grep -Fq 'config LRU_MARIE' mm/Kconfig
  grep -Fq 'CONFIG_LRU_MARIE' include/linux/lru_marie.h
  echo "==> Marie LRU $PATCH_MARIE_VERSION testing patch applied successfully"
}

report_bore_rejects() {
  local label="$1" output="$2"
  {
    echo "==> Unresolved BORE Linux port rejects: $label"
    find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
    echo
    while IFS= read -r reject; do
      echo "### ${reject#$KERNELDIR/}"
      cat "$reject"
    done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
  } | tee "$output"
}

apply_bore_patch() {
  local file="$1"

  echo "==> Applying the reviewed BORE 6.8.0-rc1 Linux 7.1.4 port"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/01-bore.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/01-bore.apply.log"
  else
    cat "$LOGDIR/01-bore.dry-run.log"
    report_bore_rejects "BORE 6.8.0-rc1 for Linux 7.1.4" \
      "$LOGDIR/01-bore-port-rejects.log"
    return 1
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check | tee "$LOGDIR/01-bore-diff-check.log"

  test -s kernel/sched/bore.c
  test -s include/linux/sched/bore.h
  grep -Fq 'struct bore_ctx' include/linux/sched.h
  grep -Fq 'sched_bore' kernel/sched/fair.c
  grep -Fq 'CONFIG_SCHED_BORE' kernel/sched/Makefile
  grep -Fq 'SCHED_BORE_VERSION' kernel/sched/bore.c
  echo "==> BORE 6.8.0-rc1 Linux port applied successfully"
}

apply_bore_sched_ext_coexistence_fix() {
  local file="$1"

  echo "==> Applying the reviewed BORE sched_ext coexistence fix"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/01-bore-sched-ext.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/01-bore-sched-ext.apply.log"
  else
    cat "$LOGDIR/01-bore-sched-ext.dry-run.log"
    report_bore_rejects "BORE sched_ext coexistence fix for Linux 7.1.4" \
      "$LOGDIR/01-bore-sched-ext-port-rejects.log"
    return 1
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check | tee "$LOGDIR/01-bore-sched-ext-diff-check.log"

  grep -Fq 'void reweight_task(struct task_struct *p, int prio)' kernel/sched/fair.c
  grep -Fq 'extern void reweight_task(struct task_struct *p, int prio);' \
    include/linux/sched/bore.h
  echo "==> BORE sched_ext coexistence fix applied successfully"
}

apply_adios_patch() {
  local file="$1" status
  local -a rejects expected

  echo "==> Applying ADIOS with Liquorix compatibility handling"
  if patch --batch --forward --strip=1 < "$file" > "$LOGDIR/03-adios.apply.log" 2>&1; then
    status=0
  else
    status=$?
  fi
  cat "$LOGDIR/03-adios.apply.log"

  if [[ $status -eq 0 ]]; then
    find "$KERNELDIR" -name '*.orig' -delete
    return 0
  fi

  mapfile -t rejects < <(find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort)
  expected=("block/elevator.c.rej")

  if [[ "${rejects[*]}" != "${expected[*]}" ]]; then
    echo "Unexpected ADIOS rejects: ${rejects[*]:-none}" >&2
    return 1
  fi

  python3 "$ROOT/scripts/apply-adios-liquorix.py" "$KERNELDIR"
  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check -- block/elevator.c

  grep -Fq 'CONFIG_MQ_IOSCHED_DEFAULT_ADIOS' block/elevator.c
  grep -Fq 'ctx.name = "adios"' block/elevator.c
  echo "==> ADIOS compatibility layer applied successfully"
}

assert_config() {
  local expected="$1"
  if ! grep -Fqx "$expected" .config; then
    echo "Required kernel configuration is missing: $expected" >&2
    grep -F "${expected%%=*}" .config || true
    return 1
  fi
}

assert_disabled_or_absent() {
  local symbol="$1"
  if grep -Eq "^CONFIG_${symbol}=[ym]$" .config; then
    echo "Kernel configuration unexpectedly enables CONFIG_${symbol}:" >&2
    grep -E "^CONFIG_${symbol}=" .config >&2 || true
    return 1
  fi
}

configure_builtin_cmdline() {
  local configured token

  configured="$(sed -n 's/^CONFIG_CMDLINE="\(.*\)"$/\1/p' .config)"
  configured="${configured% }"

  for token in "${KERNEL_DEFAULT_CMDLINE[@]}"; do
    case " $configured " in
      *" $token "*) ;;
      *) configured="${configured:+$configured }$token" ;;
    esac
  done

  scripts/config --enable CPU_MITIGATIONS
  scripts/config --enable CMDLINE_BOOL
  scripts/config --set-str CMDLINE "$configured"
  scripts/config --disable CMDLINE_OVERRIDE

  printf '%s\n' "$configured" | tee "$LOGDIR/kernel-command-line.txt"
}

assert_cmdline_token() {
  local token="$1" configured
  configured="$(sed -n 's/^CONFIG_CMDLINE="\(.*\)"$/\1/p' .config)"

  case " $configured " in
    *" $token "*) ;;
    *)
      echo "Required built-in kernel argument is missing: $token" >&2
      echo "CONFIG_CMDLINE=$configured" >&2
      return 1
      ;;
  esac
}

echo "==> Cloning current upstream Linux source tag $KERNEL_TAG"
git clone --no-checkout --depth 1 --single-branch --no-tags --branch "$KERNEL_TAG" "$KERNEL_REPO" "$KERNELDIR"
git -C "$KERNELDIR" checkout --force --detach "$KERNEL_TAG"

fetch_marie_testing_patch
fetch_bore_source
fetch_bore_sched_ext_source
download "$ADIOS_URL" "$PATCHDIR/0003-adios-3.2.0.patch"
download "$LIQUORIX_CONFIG_URL" "$WORKDIR/liquorix-amd64.config"

cd "$KERNELDIR"
apply_marie_testing_patch "$MARIE_PATCH"
apply_bore_patch "$BORE_PATCH"
apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"
apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"

cp "$WORKDIR/liquorix-amd64.config" .config

# BORE augments CFS/EEVDF. Alternative schedulers remain disabled so
# the BORE implementation selected above is the active fair scheduler path.
scripts/config --disable SCHED_ALT
scripts/config --disable SCHED_PDS
scripts/config --disable SCHED_BMQ
scripts/config --enable SCHED_BORE
scripts/config --set-val MIN_BASE_SLICE_NS 2000000

# Memory and I/O policy for responsive desktop and gaming workloads.
scripts/config --enable LRU_MARIE
scripts/config --enable LRU_GEN
scripts/config --enable LRU_GEN_ENABLED
scripts/config --enable MQ_IOSCHED_ADIOS
scripts/config --enable MQ_IOSCHED_DEFAULT_ADIOS
scripts/config --module BLK_DEV_ZRAM

# REFLEX is an external CPUFreq governor. Keep both vendor P-State drivers
# available in passive mode so REFLEX remains the active policy controller.
scripts/config --enable X86_INTEL_PSTATE
scripts/config --enable X86_AMD_PSTATE
scripts/config --set-val X86_AMD_PSTATE_DEFAULT_MODE 2

# ThinLTO is mandatory for the final kernel. These symbols only survive
# olddefconfig when Clang, LLD and the LLVM integrated assembler are active.
scripts/config --disable LTO_NONE
scripts/config --disable LTO_CLANG_FULL
scripts/config --enable LTO_CLANG_THIN

# Reproducible generic AMD64 build for LMDE. Avoid distro certificate paths and
# Rust toolchain coupling from the upstream Liquorix generated configuration.
scripts/config --set-str LOCALVERSION "-kernelnote-lqx-marie-bore-adios-thinlto"
scripts/config --disable LOCALVERSION_AUTO
scripts/config --set-str SYSTEM_TRUSTED_KEYS ""
scripts/config --set-str SYSTEM_REVOCATION_KEYS ""
scripts/config --disable RUST
configure_builtin_cmdline

# PR validation exercises the complete built-in kernel and ThinLTO link, but
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

"${MAKE[@]}" olddefconfig
"${MAKE[@]}" -s kernelrelease | tee "$LOGDIR/kernelrelease.txt"

assert_disabled_or_absent SCHED_ALT
assert_disabled_or_absent SCHED_PDS
assert_disabled_or_absent SCHED_BMQ
assert_config "CONFIG_SCHED_BORE=y"
assert_disabled_or_absent LTO_NONE
assert_disabled_or_absent LTO_CLANG_FULL
assert_disabled_or_absent CMDLINE_OVERRIDE
assert_config "CONFIG_CC_IS_CLANG=y"
assert_config "CONFIG_LD_IS_LLD=y"
assert_config "CONFIG_AS_IS_LLVM=y"
assert_config "CONFIG_LTO=y"
assert_config "CONFIG_LTO_CLANG=y"
assert_config "CONFIG_LTO_CLANG_THIN=y"
assert_config "CONFIG_LRU_MARIE=y"
assert_config "CONFIG_MQ_IOSCHED_ADIOS=y"
assert_config "CONFIG_MQ_IOSCHED_DEFAULT_ADIOS=y"
assert_config "CONFIG_X86_INTEL_PSTATE=y"
assert_config "CONFIG_X86_AMD_PSTATE=y"
assert_config "CONFIG_X86_AMD_PSTATE_DEFAULT_MODE=2"
assert_config "CONFIG_CPU_MITIGATIONS=y"
assert_config "CONFIG_CMDLINE_BOOL=y"
assert_cmdline_token "mitigations=off"
assert_cmdline_token "nowatchdog"
assert_cmdline_token "intel_pstate=passive"
assert_cmdline_token "amd_pstate=passive"

if [[ "$MODE" == "validate" ]]; then
  assert_config "CONFIG_DEBUG_INFO_NONE=y"
  assert_disabled_or_absent DEBUG_INFO
  assert_disabled_or_absent DEBUG_INFO_BTF
fi

cp .config "$LOGDIR/final.config"
{
  clang --version | head -n 1
  ld.lld --version | head -n 1
  llvm-ar --version | head -n 1
} | tee "$LOGDIR/llvm-toolchain.txt"

if [[ "$MODE" == "package" ]]; then
  echo "==> Building complete Clang ThinLTO Debian packages with $JOBS parallel jobs"
  "${MAKE[@]}" -j"$JOBS" bindeb-pkg KDEB_PKGVERSION="7.1.4-1turbodecky1"
  find "$WORKDIR" -maxdepth 1 -type f -name '*.deb' -exec cp -v {} "$ARTIFACTS/" \;
  "$ROOT/scripts/build-tuning-package.sh"
else
  echo "==> Validating built-in kernel and Clang ThinLTO link with $JOBS parallel jobs"
  "${MAKE[@]}" -j"$JOBS" bzImage
  test -s arch/x86/boot/bzImage
  test -s vmlinux
  file arch/x86/boot/bzImage vmlinux | tee "$LOGDIR/build-products.txt"
fi

echo "==> Kernelnote ThinLTO build completed successfully"
