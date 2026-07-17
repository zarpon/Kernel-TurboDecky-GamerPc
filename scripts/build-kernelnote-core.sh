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

KERNEL_TAG="v7.1.3-lqx1"
KERNEL_REPO="https://github.com/zen-kernel/zen-kernel.git"
LIQUORIX_CONFIG_URL="https://raw.githubusercontent.com/damentz/liquorix-package/56f0e85662990ee20b4ea10465a41a23b65ace2c/linux-liquorix/debian/config/kernelarch-x86/config-arch-64"
ADIOS_URL="https://raw.githubusercontent.com/firelzrd/adios/08bf078aac99075a0bef73c2b2497574a82e4c41/patches/stable/0001-linux6.19.3-ADIOS-3.2.0.patch"

# Correct Infinity scheduler v3 patch for Linux 7.1. This is the single
# cumulative patch from the upstream v3/stable/linux-7.1-infinity tree; it
# includes the CPU, futex and RT hooks. No separate Infinity GPU series is used.
INFINITY_REPO="https://github.com/galpt/infinity-scheduler.git"
INFINITY_BRANCH="v3"
INFINITY_COMMIT="2cc72b8a3caf4ed75638893306c3e319819e2a42"
INFINITY_PATCH_PATH="patches/stable/linux-7.1-infinity/0001-infinity-scheduler.patch"
INFINITY_DIR="$WORKDIR/infinity-scheduler"
INFINITY_PATCH="$PATCHDIR/0001-infinity-scheduler.patch"

# Marie is fetched as a pinned local Git checkout rather than through a raw
# patch URL. Only the exact patch blob is materialized in the workspace.
MARIE_REPO="https://github.com/firelzrd/lru_marie.git"
MARIE_COMMIT="4d57ede4ab9b2000ae9ddc25714b8ac219671d35"
MARIE_PATCH_PATH="patches/testing/0001-linux7.1-rc5-lru_marie-0.7.7.patch"
MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"

# Keep the existing Liquorix built-in arguments and append these canonical
# kernel parameters. CMDLINE_OVERRIDE stays disabled so bootloader parameters
# such as root=, resume= and console= are preserved.
KERNEL_DEFAULT_CMDLINE=(
  "mitigations=off"
  "nowatchdog"
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
  echo "==> Fetching pinned Marie LRU 0.7.7 testing source locally"
  rm -rf "$MARIEDIR"
  git init --quiet "$MARIEDIR"
  git -C "$MARIEDIR" remote add origin "$MARIE_REPO"
  git -C "$MARIEDIR" config remote.origin.promisor true
  git -C "$MARIEDIR" config remote.origin.partialclonefilter blob:none
  git -C "$MARIEDIR" fetch --no-tags --depth=1 --filter=blob:none origin "$MARIE_COMMIT" \
    2>&1 | tee "$LOGDIR/02-lru-marie-fetch.log"

  git -C "$MARIEDIR" show "FETCH_HEAD:$MARIE_PATCH_PATH" > "$MARIE_PATCH"
  test -s "$MARIE_PATCH"
  grep -Fq 'Subject: [PATCH] linux7.1-rc5-lru_marie-0.7.7' "$MARIE_PATCH"

  {
    echo "Marie source policy: testing-compatible"
    echo "Repository: firelzrd/lru_marie"
    echo "Commit: $MARIE_COMMIT"
    echo "Path: $MARIE_PATCH_PATH"
    echo "SHA256: $(sha256sum "$MARIE_PATCH" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout; no raw patch URL"
  } | tee "$LOGDIR/02-lru-marie-provenance.txt"
}

fetch_infinity_patch() {
  echo "==> Fetching the pinned correct Infinity CPU scheduler patch locally"
  rm -rf "$INFINITY_DIR"
  git init --quiet "$INFINITY_DIR"
  git -C "$INFINITY_DIR" remote add origin "$INFINITY_REPO"
  git -C "$INFINITY_DIR" config remote.origin.promisor true
  git -C "$INFINITY_DIR" config remote.origin.partialclonefilter blob:none
  git -C "$INFINITY_DIR" fetch --no-tags --depth=1 --filter=blob:none origin "$INFINITY_COMMIT" \
    2>&1 | tee "$LOGDIR/01-infinity-fetch.log"

  git -C "$INFINITY_DIR" show "FETCH_HEAD:$INFINITY_PATCH_PATH" > "$INFINITY_PATCH"
  test -s "$INFINITY_PATCH"
  grep -Fq 'diff --git a/kernel/sched/infinity_sched.c b/kernel/sched/infinity_sched.c' \
    "$INFINITY_PATCH"
  grep -Fq 'infinity_consume' "$INFINITY_PATCH"
  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' "$INFINITY_PATCH"
  grep -Fq 'infinity_rt_consume' "$INFINITY_PATCH"
  grep -Fq 'futex_waiting' "$INFINITY_PATCH"
  grep -Fq 'Subject: [PATCH] infinity-scheduler v3' "$INFINITY_PATCH"

  {
    echo "Component: Infinity scheduler v3"
    echo "Repository: $INFINITY_REPO"
    echo "Branch: $INFINITY_BRANCH"
    echo "Commit: $INFINITY_COMMIT"
    echo "Path: $INFINITY_PATCH_PATH"
    echo "SHA256: $(sha256sum "$INFINITY_PATCH" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout"
  } | tee "$LOGDIR/01-infinity-provenance.txt"
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

  echo "==> Applying local Marie LRU 0.7.7 testing patch for Linux 7.1"
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

  grep -Fq '0.7.7' mm/lru_marie/version.h
  grep -Fq 'config LRU_MARIE' mm/Kconfig
  grep -Fq 'CONFIG_LRU_MARIE' include/linux/lru_marie.h
  echo "==> Marie LRU 0.7.7 testing patch applied successfully"
}

report_infinity_rejects() {
  local label="$1" output="$2"
  {
    echo "==> Unresolved Infinity port rejects: $label"
    find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
    echo
    while IFS= read -r reject; do
      echo "### ${reject#$KERNELDIR/}"
      cat "$reject"
    done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
  } | tee "$output"
}

apply_infinity_patch() {
  local file="$1" status=0

  echo "==> Applying the correct Infinity v3 CPU/RT scheduler patch"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/01-infinity.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/01-infinity.apply.log"
  else
    cat "$LOGDIR/01-infinity.dry-run.log"
    echo "==> Retrying Infinity with controlled port fuzz <= 3"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/01-infinity.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/01-infinity.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      report_infinity_rejects "correct CPU scheduler patch" \
        "$LOGDIR/01-infinity-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check | tee "$LOGDIR/01-infinity-diff-check.log"

  test -s kernel/sched/infinity_sched.c
  test -s kernel/sched/infinity_sched.h
  grep -Fq 'struct infinity_ctx' include/linux/sched.h
  grep -Fq 'infinity_slice' kernel/sched/fair.c
  grep -Fq 'infinity_consume' kernel/sched/fair.c
  grep -Fq 'infinity_rt_consume' kernel/sched/rt.c
  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' include/uapi/linux/sched.h
  grep -Fq 'futex_waiting' kernel/futex/waitwake.c
  grep -Fq 'Infinity scheduler active' kernel/sched/infinity_sched.c
  echo "==> Correct Infinity v3 CPU/RT scheduler patch applied successfully"
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

echo "==> Cloning official Liquorix source tag $KERNEL_TAG"
git clone --no-checkout --depth 1 --single-branch --no-tags --branch "$KERNEL_TAG" "$KERNEL_REPO" "$KERNELDIR"
git -C "$KERNELDIR" checkout --force --detach "$KERNEL_TAG"

fetch_marie_testing_patch
fetch_infinity_patch
download "$ADIOS_URL" "$PATCHDIR/0003-adios-3.2.0.patch"
download "$LIQUORIX_CONFIG_URL" "$WORKDIR/liquorix-amd64.config"

cd "$KERNELDIR"
apply_marie_testing_patch "$MARIE_PATCH"
apply_infinity_patch "$INFINITY_PATCH"
apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"

cp "$WORKDIR/liquorix-amd64.config" .config

# Infinity v3 is integrated directly into CFS/EEVDF and the RT class.
# Liquorix alternative schedulers must remain disabled so Infinity is effective.
scripts/config --disable SCHED_ALT
scripts/config --disable SCHED_PDS
scripts/config --disable SCHED_BMQ
scripts/config --set-val MIN_BASE_SLICE_NS 2000000

# Memory and I/O policy for responsive desktop and gaming workloads.
scripts/config --enable LRU_MARIE
scripts/config --enable LRU_GEN
scripts/config --enable LRU_GEN_ENABLED
scripts/config --enable MQ_IOSCHED_ADIOS
scripts/config --enable MQ_IOSCHED_DEFAULT_ADIOS
scripts/config --module BLK_DEV_ZRAM

# ThinLTO is mandatory for the final kernel. These symbols only survive
# olddefconfig when Clang, LLD and the LLVM integrated assembler are active.
scripts/config --disable LTO_NONE
scripts/config --disable LTO_CLANG_FULL
scripts/config --enable LTO_CLANG_THIN

# Reproducible generic AMD64 build for LMDE. Avoid distro certificate paths and
# Rust toolchain coupling from the upstream Liquorix generated configuration.
scripts/config --set-str LOCALVERSION "-kernelnote-lqx-marie-infinity-adios-thinlto"
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
assert_disabled_or_absent SCHED_BORE
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
assert_config "CONFIG_CPU_MITIGATIONS=y"
assert_config "CONFIG_CMDLINE_BOOL=y"
assert_cmdline_token "mitigations=off"
assert_cmdline_token "nowatchdog"

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
  "${MAKE[@]}" -j"$JOBS" bindeb-pkg KDEB_PKGVERSION="7.1.3-1turbodecky1"
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
