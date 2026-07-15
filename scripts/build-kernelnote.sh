#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-validate}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$ROOT/work"
LOGDIR="$ROOT/logs"
ARTIFACTS="$ROOT/artifacts"
PATCHDIR="$WORKDIR/patches"
KERNELDIR="$WORKDIR/linux"
JOBS="${JOBS:-$(nproc)}"

KERNEL_TAG="v7.1.3-lqx1"
KERNEL_REPO="https://github.com/zen-kernel/zen-kernel.git"
LIQUORIX_CONFIG_URL="https://raw.githubusercontent.com/damentz/liquorix-package/56f0e85662990ee20b4ea10465a41a23b65ace2c/linux-liquorix/debian/config/kernelarch-x86/config-arch-64"
BORE_URL="https://raw.githubusercontent.com/firelzrd/bore-scheduler/16bf5baebbb42cdba393c501ba9c2af5f84e4749/patches/testing/0001-linux7.1-rc1-bore-6.8.0-rc1.patch"
MARIE_URL="https://raw.githubusercontent.com/firelzrd/lru_marie/4d57ede4ab9b2000ae9ddc25714b8ac219671d35/patches/testing/0001-linux7.1-rc5-lru_marie-0.7.7.patch"
ADIOS_URL="https://raw.githubusercontent.com/firelzrd/adios/08bf078aac99075a0bef73c2b2497574a82e4c41/patches/stable/0001-linux6.19.3-ADIOS-3.2.0.patch"

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
  curl --fail --location --retry 4 --retry-delay 3 --connect-timeout 30 "$url" -o "$output"
  sha256sum "$output" | tee -a "$LOGDIR/downloads.sha256"
}

apply_patch_file() {
  local label="$1" file="$2"
  echo "==> Checking $label"
  if ! patch --batch --forward --strip=1 --dry-run < "$file" > "$LOGDIR/${label}.dry-run.log" 2>&1; then
    cat "$LOGDIR/${label}.dry-run.log"
    return 1
  fi
  echo "==> Applying $label"
  patch --batch --forward --strip=1 < "$file" | tee "$LOGDIR/${label}.apply.log"
}

apply_bore_patch() {
  local file="$1" status
  local -a rejects expected

  echo "==> Applying BORE with Liquorix compatibility handling"
  if patch --batch --forward --strip=1 < "$file" > "$LOGDIR/01-bore.apply.log" 2>&1; then
    status=0
  else
    status=$?
  fi
  cat "$LOGDIR/01-bore.apply.log"

  if [[ $status -eq 0 ]]; then
    return 0
  fi

  mapfile -t rejects < <(find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort)
  expected=(
    "kernel/sched/debug.c.rej"
    "kernel/sched/fair.c.rej"
  )

  if [[ "${rejects[*]}" != "${expected[*]}" ]]; then
    echo "Unexpected BORE rejects: ${rejects[*]:-none}" >&2
    return 1
  fi

  python3 "$ROOT/scripts/apply-bore-liquorix.py" "$KERNELDIR"
  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check -- kernel/sched/fair.c kernel/sched/debug.c

  grep -Fq 'CONFIG_SCHED_BORE' kernel/sched/fair.c
  grep -Fq 'sched_min_base_slice_fops' kernel/sched/debug.c
  echo "==> BORE compatibility layer applied successfully"
}

assert_config() {
  local expected="$1"
  if ! grep -Fqx "$expected" .config; then
    echo "Required kernel configuration is missing: $expected" >&2
    grep -F "${expected%%=*}" .config || true
    return 1
  fi
}

echo "==> Cloning official Liquorix source tag $KERNEL_TAG"
git clone --depth 1 --branch "$KERNEL_TAG" "$KERNEL_REPO" "$KERNELDIR"

download "$BORE_URL" "$PATCHDIR/0001-bore-6.8.0-rc1.patch"
download "$MARIE_URL" "$PATCHDIR/0002-lru-marie-0.7.7.patch"
download "$ADIOS_URL" "$PATCHDIR/0003-adios-3.2.0.patch"
download "$LIQUORIX_CONFIG_URL" "$WORKDIR/liquorix-amd64.config"

cd "$KERNELDIR"
apply_bore_patch "$PATCHDIR/0001-bore-6.8.0-rc1.patch"
apply_patch_file "02-lru-marie" "$PATCHDIR/0002-lru-marie-0.7.7.patch"
apply_patch_file "03-adios" "$PATCHDIR/0003-adios-3.2.0.patch"

cp "$WORKDIR/liquorix-amd64.config" .config

# BORE enhances the normal CFS/EEVDF path. Liquorix PDS/BMQ must be disabled,
# otherwise BORE would be present in the source but not be the effective scheduler.
scripts/config --disable SCHED_ALT
scripts/config --disable SCHED_PDS
scripts/config --disable SCHED_BMQ
scripts/config --enable SCHED_BORE
scripts/config --set-val MIN_BASE_SLICE_NS 2000000

# Memory and I/O policy requested for the HP 240 G4 notebook.
scripts/config --enable LRU_MARIE
scripts/config --enable LRU_GEN
scripts/config --enable LRU_GEN_ENABLED
scripts/config --enable MQ_IOSCHED_ADIOS
scripts/config --enable MQ_IOSCHED_DEFAULT_ADIOS
scripts/config --module BLK_DEV_ZRAM

# Reproducible generic AMD64 build for LMDE. Avoid distro certificate paths and
# Rust toolchain coupling from the upstream Liquorix generated configuration.
scripts/config --set-str LOCALVERSION "-kernelnote-lqx-marie-bore-adios"
scripts/config --disable LOCALVERSION_AUTO
scripts/config --set-str SYSTEM_TRUSTED_KEYS ""
scripts/config --set-str SYSTEM_REVOCATION_KEYS ""
scripts/config --disable RUST

make olddefconfig
make -s kernelrelease | tee "$LOGDIR/kernelrelease.txt"

assert_config "# CONFIG_SCHED_ALT is not set"
assert_config "# CONFIG_SCHED_PDS is not set"
assert_config "CONFIG_SCHED_BORE=y"
assert_config "CONFIG_LRU_MARIE=y"
assert_config "CONFIG_MQ_IOSCHED_ADIOS=y"
assert_config "CONFIG_MQ_IOSCHED_DEFAULT_ADIOS=y"

cp .config "$LOGDIR/final.config"

echo "==> Building with $JOBS parallel jobs"
if [[ "$MODE" == "package" ]]; then
  make -j"$JOBS" bindeb-pkg KDEB_PKGVERSION="7.1.3-1kernelnote1"
  find "$WORKDIR" -maxdepth 1 -type f -name '*.deb' -exec cp -v {} "$ARTIFACTS/" \;
  "$ROOT/scripts/build-tuning-package.sh"
else
  make -j"$JOBS" bzImage modules
fi

echo "==> Kernelnote build completed successfully"
