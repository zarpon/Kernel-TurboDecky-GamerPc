#!/usr/bin/env bash
set -Eeuo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
helper="$root/packaging/configure-zram-ir"
zram_generator_dropin="$root/packaging/90-turbodecky-zram.conf"
zram_setup_dropin="$root/packaging/90-turbodecky-zram-ir.conf"
sandbox="$(mktemp -d)"
trap 'rm -rf "$sandbox"' EXIT

fail() {
  echo "runtime tuning validation failed: $*" >&2
  exit 1
}

require_line() {
  local file="$1"
  local line="$2"
  grep -Fxq -- "$line" "$file" || fail "missing '$line' in ${file#$root/}"
}

require_value() {
  local file="$1"
  local value="$2"
  [[ "$(<"$file")" == "$value" ]] || fail "expected '$value' in $file"
}

bash -n "$root/scripts/build-tuning-package.sh"
sh -n "$helper"

require_line "$zram_generator_dropin" "[zram0]"
require_line "$zram_generator_dropin" "compression-algorithm = lz4 zstd"
require_line "$zram_setup_dropin" "[Service]"
require_line "$zram_setup_dropin" "ExecStartPre=/usr/lib/turbodecky/configure-zram-ir %I"

# A distro may configure zram0 with zstd in its main generator configuration.
# The TurboDecky drop-in must replace only the compression policy, preserving
# the size and swap settings selected by the distribution.
python3 - "$zram_generator_dropin" <<'PY'
import configparser
import sys

base = """\
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
swap-priority = 100
fs-type = swap
"""

parser = configparser.ConfigParser(interpolation=None)
parser.read_string(base)
parser.read(sys.argv[1], encoding="utf-8")

zram0 = parser["zram0"]
assert zram0["compression-algorithm"] == "lz4 zstd"
assert zram0["zram-size"] == "ram / 2"
assert zram0["swap-priority"] == "100"
assert zram0["fs-type"] == "swap"
PY

# Exercise the exact UDEV helper against regular files standing in for sysfs
# and procfs. An uninitialized device must receive LZ4 + ZSTD priority 1.
mkdir -p "$sandbox/sys/block/zram0" "$sandbox/proc/sys/vm" "$sandbox/bin"
printf '0\n' > "$sandbox/sys/block/zram0/initstate"
printf 'zstd lz4\n' > "$sandbox/sys/block/zram0/comp_algorithm"
printf 'zstd lz4\n' > "$sandbox/sys/block/zram0/recomp_algorithm"
printf '0\n' > "$sandbox/proc/sys/vm/zram_recomp_immediate"
printf '#!/bin/sh\nexit 0\n' > "$sandbox/bin/logger"
chmod +x "$sandbox/bin/logger"

PATH="$sandbox/bin:$PATH" \
  TURBODECKY_SYS_ROOT="$sandbox/sys" \
  TURBODECKY_PROC_SYS_ROOT="$sandbox/proc/sys" \
  sh "$helper" zram0
require_value "$sandbox/proc/sys/vm/zram_recomp_immediate" "1"
require_value "$sandbox/sys/block/zram0/comp_algorithm" "lz4"
require_value "$sandbox/sys/block/zram0/recomp_algorithm" "algo=zstd priority=1"

# A later UDEV change event must reassert the sysctl but must not reset an
# active zram swap or replace the compression algorithms it already uses.
printf '1\n' > "$sandbox/sys/block/zram0/initstate"
printf 'already-active-primary\n' > "$sandbox/sys/block/zram0/comp_algorithm"
printf 'already-active-secondary\n' > "$sandbox/sys/block/zram0/recomp_algorithm"
printf '0\n' > "$sandbox/proc/sys/vm/zram_recomp_immediate"
PATH="$sandbox/bin:$PATH" \
  TURBODECKY_SYS_ROOT="$sandbox/sys" \
  TURBODECKY_PROC_SYS_ROOT="$sandbox/proc/sys" \
  sh "$helper" zram0
require_value "$sandbox/proc/sys/vm/zram_recomp_immediate" "1"
require_value "$sandbox/sys/block/zram0/comp_algorithm" "already-active-primary"
require_value "$sandbox/sys/block/zram0/recomp_algorithm" "already-active-secondary"

# Build the tuning package in an isolated tree and verify that the runtime
# payload and post-install daemon reload are actually delivered in the DEB.
TURBODECKY_ARTIFACTS="$sandbox/artifacts" \
  TURBODECKY_TUNING_PKGROOT="$sandbox/pkgroot" \
  "$root/scripts/build-tuning-package.sh"
deb="$sandbox/artifacts/turbodecky-tuning_1.3.1_all.deb"
[[ -s "$deb" ]] || fail "tuning package was not built"
[[ "$(dpkg-deb -f "$deb" Version)" == "1.3.1" ]] || fail "unexpected tuning package version"

for payload in \
  './usr/lib/turbodecky/configure-zram-ir' \
  './usr/lib/systemd/zram-generator.conf.d/90-turbodecky-zram.conf' \
  './usr/lib/systemd/system/systemd-zram-setup@.service.d/90-turbodecky-zram-ir.conf'; do
  dpkg-deb -c "$deb" | awk '{print $6}' | grep -Fxq -- "$payload" \
    || fail "package is missing $payload"
done

control_dir="$sandbox/control"
dpkg-deb -e "$deb" "$control_dir"
sh -n "$control_dir/postinst"
grep -Fq 'systemctl daemon-reload' "$control_dir/postinst" \
  || fail "postinst does not reload systemd units"

echo "runtime tuning validation passed"
