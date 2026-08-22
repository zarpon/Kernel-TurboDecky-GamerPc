#!/usr/bin/env bash
set -Eeuo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
helper="$root/packaging/configure-zram-ir"
zram_generator_dropin="$root/packaging/90-turbodecky-zram.conf"
zram_setup_dropin="$root/packaging/90-turbodecky-zram-ir.conf"
runtime_policy="$root/packaging/99-kernelnote.conf"
thp_policy="$root/packaging/99-kernelnote-thp.conf"
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
require_line "$runtime_policy" "vm.vfs_cache_pressure = 85"

require_line "$thp_policy" "w- /sys/kernel/mm/transparent_hugepage/enabled - - - - madvise"
require_line "$thp_policy" "w- /sys/kernel/mm/transparent_hugepage/defrag - - - - defer+madvise"
require_line "$thp_policy" "w- /sys/kernel/mm/transparent_hugepage/shmem_enabled - - - - advise"
require_line "$thp_policy" "w- /sys/kernel/mm/transparent_hugepage/khugepaged/defrag - - - - 0"
require_line "$thp_policy" "w- /sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_none - - - - 384"
require_line "$thp_policy" "w- /sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_swap - - - - 16"

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

# Parse and apply the shipped tmpfiles policy in an isolated root. The
# policy uses w- so it is also applied during package installation, without
# failing on kernels that do not expose one of these sysfs nodes.
if command -v systemd-tmpfiles >/dev/null 2>&1; then
  rootfs="$sandbox/rootfs"
  install -D -m 0644 "$thp_policy" \
    "$rootfs/usr/lib/tmpfiles.d/99-turbodecky-thp.conf"
  while read -r path; do
    install -D -m 0644 /dev/null "$rootfs$path"
  done <<'EOF'
/sys/kernel/mm/transparent_hugepage/enabled
/sys/kernel/mm/transparent_hugepage/defrag
/sys/kernel/mm/transparent_hugepage/shmem_enabled
/sys/kernel/mm/transparent_hugepage/khugepaged/defrag
/sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_none
/sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_swap
EOF
  systemd-tmpfiles --create --root="$rootfs"
  require_value "$rootfs/sys/kernel/mm/transparent_hugepage/enabled" "madvise"
  require_value "$rootfs/sys/kernel/mm/transparent_hugepage/defrag" "defer+madvise"
  require_value "$rootfs/sys/kernel/mm/transparent_hugepage/shmem_enabled" "advise"
  require_value "$rootfs/sys/kernel/mm/transparent_hugepage/khugepaged/defrag" "0"
  require_value "$rootfs/sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_none" "384"
  require_value "$rootfs/sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_swap" "16"
fi

# Deterministic admission-control simulation for one 2 MiB x86 THP. This is
# not a hardware FPS benchmark: it proves the shipped limits accept the
# configured 384-hole/16-swapped candidate while retaining explicit bounds
# against candidates that exceed the configured khugepaged limits.
python3 - "$thp_policy" <<'PY'
from dataclasses import dataclass
from pathlib import Path
import sys

PTE_PER_THP = 512
PAGE_SIZE = 4096


def tmpfiles_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        fields = raw_line.split()
        if len(fields) == 7 and fields[0] in {"w-", "w!"}:
            values[fields[1]] = fields[-1]
    return values


@dataclass(frozen=True)
class Policy:
    max_none: int
    max_swap: int


def eligible(policy: Policy, *, none: int, swap: int) -> bool:
    present = PTE_PER_THP - none - swap
    assert present >= 0
    return none <= policy.max_none and swap <= policy.max_swap


values = tmpfiles_values(Path(sys.argv[1]))
assert values["/sys/kernel/mm/transparent_hugepage/enabled"] == "madvise"
assert values["/sys/kernel/mm/transparent_hugepage/defrag"] == "defer+madvise"
assert values["/sys/kernel/mm/transparent_hugepage/shmem_enabled"] == "advise"
assert values["/sys/kernel/mm/transparent_hugepage/khugepaged/defrag"] == "0"
proposed = Policy(
    max_none=int(values["/sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_none"]),
    max_swap=int(values["/sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_swap"]),
)
assert proposed == Policy(max_none=384, max_swap=16)

legacy = Policy(max_none=64, max_swap=0)
assert eligible(legacy, none=64, swap=0)
assert eligible(proposed, none=384, swap=16)
assert not eligible(legacy, none=384, swap=0)
assert eligible(proposed, none=384, swap=0)
assert not eligible(legacy, none=0, swap=16)
assert eligible(proposed, none=0, swap=16)
assert not eligible(proposed, none=385, swap=0)
assert not eligible(proposed, none=0, swap=17)

legacy_zero_fill = legacy.max_none * PAGE_SIZE
proposed_zero_fill = proposed.max_none * PAGE_SIZE
legacy_swap_bytes = legacy.max_swap * PAGE_SIZE
proposed_swap_bytes = proposed.max_swap * PAGE_SIZE
assert proposed_zero_fill - legacy_zero_fill == 1_310_720
assert proposed_swap_bytes - legacy_swap_bytes == 65_536

print(
    "THP admission simulation passed: zero-fill cap "
    f"{legacy_zero_fill / 1024**2:.2f} MiB -> "
    f"{proposed_zero_fill / 1024**2:.2f} MiB; "
    f"swap candidate cap {legacy_swap_bytes // 1024} KiB -> "
    f"{proposed_swap_bytes // 1024} KiB"
)
PY

# Build the tuning package in an isolated tree and verify that the runtime
# payload and post-install daemon reload are actually delivered in the DEB.
TURBODECKY_ARTIFACTS="$sandbox/artifacts" \
  TURBODECKY_TUNING_PKGROOT="$sandbox/pkgroot" \
  "$root/scripts/build-tuning-package.sh"
deb="$sandbox/artifacts/turbodecky-tuning_1.3.3_all.deb"
[[ -s "$deb" ]] || fail "tuning package was not built"
[[ "$(dpkg-deb -f "$deb" Version)" == "1.3.3" ]] || fail "unexpected tuning package version"

for payload in \
  './etc/sysctl.d/99-turbodecky.conf' \
  './usr/lib/turbodecky/configure-zram-ir' \
  './usr/lib/systemd/zram-generator.conf.d/90-turbodecky-zram.conf' \
  './usr/lib/systemd/system/systemd-zram-setup@.service.d/90-turbodecky-zram-ir.conf' \
  './usr/lib/tmpfiles.d/99-turbodecky-thp.conf'; do
  dpkg-deb -c "$deb" | awk '{print $6}' | grep -Fxq -- "$payload" \
    || fail "package is missing $payload"
done

control_dir="$sandbox/control"
dpkg-deb -e "$deb" "$control_dir"
sh -n "$control_dir/postinst"
grep -Fq 'systemctl daemon-reload' "$control_dir/postinst" \
  || fail "postinst does not reload systemd units"
grep -Fq 'systemd-tmpfiles --create /usr/lib/tmpfiles.d/99-turbodecky-thp.conf' "$control_dir/postinst" \
  || fail "postinst does not apply the THP policy"

package_root="$sandbox/package-root"
dpkg-deb -x "$deb" "$package_root"
cmp -s "$runtime_policy" "$package_root/etc/sysctl.d/99-turbodecky.conf" \
  || fail "package does not contain the expected sysctl policy"
cmp -s "$thp_policy" "$package_root/usr/lib/tmpfiles.d/99-turbodecky-thp.conf" \
  || fail "package does not contain the expected THP policy"

echo "runtime tuning validation passed"
