#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="${TURBODECKY_ARTIFACTS:-$ROOT/artifacts}"
PKGROOT="${TURBODECKY_TUNING_PKGROOT:-$ROOT/work/turbodecky-tuning}"
TUNING_VERSION="1.5.1"

nap_tools="$ROOT/.resolved-nap-tools"
nap_require_resolved=(--require-resolved)
if [[ "${NAP_TOOLS_TEST_OFFLINE:-0}" == 1 ]]; then
  [[ ! -d "$ROOT/work/linux" ]] || {
    echo "Offline NAP fixtures are not permitted for production kernel packages" >&2
    exit 1
  }
  nap_tools="$ROOT/nap-tools"
  nap_require_resolved=()
else
  python3 "$ROOT/nap-tools/refresh-tools.py" --output "$nap_tools" \
    --record "$ROOT/logs/nap-tools-upstream.json"
  NAP_TOOLS_TEST_SOURCE_DIR="$nap_tools" python3 "$ROOT/tests/test_nap_tools.py"
  # A changed upstream snapshot must be recognized as a package update even
  # when the downstream tuning version has not changed between daily builds.
  TUNING_VERSION+="$(python3 - "$nap_tools/UPSTREAM.json" <<'PY'
import json
import sys
with open(sys.argv[1]) as stream:
    manifest = json.load(stream)
print(f"+nap.{manifest['commit_timestamp']}.{manifest['commit'][:12]}")
PY
)"
fi

# Production package builds have already emitted final.config, modules.order and
# linux-image. Validate that complete payload before adding the tuning package.
# Standalone tuning-package tests intentionally have none of those kernel files.
if [[ -s "$ROOT/logs/final.config" && -s "$ROOT/work/linux/modules.order" ]] && \
   compgen -G "$ARTIFACTS/linux-image-*.deb" >/dev/null; then
  python3 "$ROOT/scripts/validate-generic-pc-package.py" \
    --config "$ROOT/logs/final.config" \
    --modules-order "$ROOT/work/linux/modules.order" \
    --artifacts "$ARTIFACTS" \
    --report "$ROOT/logs/generic-pc-package-coverage.txt"
fi

rm -rf "$PKGROOT"
install -d "$PKGROOT/DEBIAN" \
           "$PKGROOT/etc/sysctl.d" \
           "$PKGROOT/etc/udev/rules.d" \
           "$PKGROOT/etc/default/grub.d" \
           "$PKGROOT/usr/lib/tmpfiles.d" \
           "$PKGROOT/usr/lib/systemd/zram-generator.conf.d" \
           "$PKGROOT/usr/lib/systemd/system/systemd-zram-setup@.service.d" \
           "$PKGROOT/usr/lib/turbodecky" \
           "$PKGROOT/usr/lib/gaming-swap" \
           "$PKGROOT/usr/lib/systemd/system"

install -m 0755 "$ROOT/packaging/configure-gaming-swap" \
  "$PKGROOT/usr/lib/gaming-swap/configure"
install -m 0644 "$ROOT/packaging/gaming-zswap.service" \
  "$PKGROOT/usr/lib/systemd/system/gaming-zswap.service"

# Production packages use the model in the patched kernel, never an unrelated
# prebuilt viewer. Standalone package tests can use the pinned upstream viewer.
if [[ -d "$ROOT/work/linux" ]]; then
  python3 "$nap_tools/install-tools.py" --source-dir "$nap_tools" \
    "${nap_require_resolved[@]}" --destdir "$PKGROOT" \
    --kernel-dir "$ROOT/work/linux/drivers/cpuidle/governors/nap"
else
  python3 "$nap_tools/install-tools.py" --source-dir "$nap_tools" \
    "${nap_require_resolved[@]}" --destdir "$PKGROOT" \
    --allow-prebuilt-viewer
fi

install -m 0644 "$ROOT/packaging/99-kernelnote.conf" \
  "$PKGROOT/etc/sysctl.d/99-turbodecky.conf"
install -m 0644 "$ROOT/packaging/65-kernelnote-adios.rules" \
  "$PKGROOT/etc/udev/rules.d/65-turbodecky-adios.rules"
install -m 0644 "$ROOT/packaging/60-kernelnote-zram-ir.rules" \
  "$PKGROOT/etc/udev/rules.d/60-turbodecky-zram-ir.rules"
install -m 0755 "$ROOT/packaging/configure-zram-ir" \
  "$PKGROOT/usr/lib/turbodecky/configure-zram-ir"
install -m 0644 "$ROOT/packaging/90-turbodecky-zram.conf" \
  "$PKGROOT/usr/lib/systemd/zram-generator.conf.d/90-turbodecky-zram.conf"
install -m 0644 "$ROOT/packaging/90-turbodecky-zram-ir.conf" \
  "$PKGROOT/usr/lib/systemd/system/systemd-zram-setup@.service.d/90-turbodecky-zram-ir.conf"
install -m 0644 "$ROOT/packaging/99-kernelnote-grub.cfg" \
  "$PKGROOT/etc/default/grub.d/99-turbodecky.cfg"
install -m 0644 "$ROOT/packaging/99-kernelnote-thp.conf" \
  "$PKGROOT/usr/lib/tmpfiles.d/99-turbodecky-thp.conf"

cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: turbodecky-tuning
Version: ${TUNING_VERSION}
Section: kernel
Priority: optional
Architecture: all
Maintainer: TurboDecky GamerPc <noreply@localhost>
Depends: clang, llvm, lld, make, procps, udev, python3, util-linux, coreutils, btrfs-progs, systemd
Recommends: grub2-common
Description: Runtime, boot and external-module defaults for TurboDecky GamerPc
 Sets CAST memory defaults, selects ADIOS, applies the requested Transparent
 Hugepage policy, appends performance parameters to GRUB, disables zram and
 migrates swapfiles to /home with 75 percent RAM capacity and LZ4 zswap,
 preserves NAP learning across boots and installs napctl and an offline viewer,
 and installs the LLVM toolchain required to compile VirtualBox,
 DKMS and other external modules against this Clang kernel.
EOF

cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
/usr/lib/nap/configure-services install
/usr/lib/gaming-swap/configure
sysctl --system >/dev/null 2>&1 || true
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload >/dev/null 2>&1 || true
fi
udevadm control --reload-rules >/dev/null 2>&1 || true
systemd-tmpfiles --create /usr/lib/tmpfiles.d/99-turbodecky-thp.conf >/dev/null 2>&1 || true
udevadm trigger --subsystem-match=block --action=change >/dev/null 2>&1 || true
if command -v update-grub >/dev/null 2>&1; then
  update-grub >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postinst"

cat > "$PKGROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
case "$1" in
  remove|deconfigure) /usr/lib/nap/configure-services remove ;;
esac
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/prerm"

cat > "$PKGROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload >/dev/null 2>&1 || true
fi
if command -v update-grub >/dev/null 2>&1; then
  update-grub >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postrm"

mkdir -p "$ARTIFACTS"
dpkg-deb --build --root-owner-group "$PKGROOT" \
  "$ARTIFACTS/turbodecky-tuning_${TUNING_VERSION}_all.deb"
