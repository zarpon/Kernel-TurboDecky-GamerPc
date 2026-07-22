#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="${TURBODECKY_ARTIFACTS:-$ROOT/artifacts}"
PKGROOT="${TURBODECKY_TUNING_PKGROOT:-$ROOT/work/turbodecky-tuning}"
TUNING_VERSION="1.3.1"

rm -rf "$PKGROOT"
install -d "$PKGROOT/DEBIAN" \
           "$PKGROOT/etc/sysctl.d" \
           "$PKGROOT/etc/udev/rules.d" \
           "$PKGROOT/etc/default/grub.d" \
           "$PKGROOT/usr/lib/tmpfiles.d" \
           "$PKGROOT/usr/lib/systemd/zram-generator.conf.d" \
           "$PKGROOT/usr/lib/systemd/system/systemd-zram-setup@.service.d" \
           "$PKGROOT/usr/lib/turbodecky"

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
Depends: clang, llvm, lld, make, procps, udev, systemd | systemd-standalone-tmpfiles
Recommends: grub2-common
Description: Runtime, boot and external-module defaults for TurboDecky GamerPc
 Sets Marie memory defaults, selects ADIOS, applies the requested Transparent
 Hugepage policy, appends performance parameters to GRUB, configures every new
 zram device for ZRAM-IR with LZ4 primary compression and ZSTD priority-1
 recompression, and installs the LLVM toolchain required to compile VirtualBox,
 DKMS and other external modules against this Clang kernel.
EOF

cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
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
