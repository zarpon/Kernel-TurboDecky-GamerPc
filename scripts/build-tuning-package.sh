#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="$ROOT/artifacts"
PKGROOT="$ROOT/work/kernelnote-tuning"

rm -rf "$PKGROOT"
install -d "$PKGROOT/DEBIAN" \
           "$PKGROOT/etc/sysctl.d" \
           "$PKGROOT/etc/udev/rules.d"

install -m 0644 "$ROOT/packaging/99-kernelnote.conf" \
  "$PKGROOT/etc/sysctl.d/99-kernelnote.conf"
install -m 0644 "$ROOT/packaging/65-kernelnote-adios.rules" \
  "$PKGROOT/etc/udev/rules.d/65-kernelnote-adios.rules"

cat > "$PKGROOT/DEBIAN/control" <<'EOF'
Package: kernelnote-tuning
Version: 1.0.0
Section: kernel
Priority: optional
Architecture: all
Maintainer: Kernelnote <noreply@localhost>
Depends: procps, udev
Description: Runtime defaults for the Kernelnote Liquorix kernel
 Sets vm.swappiness=1, vm.page-cluster=0 and selects ADIOS on every
 compatible block device through a udev rule.
EOF

cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
sysctl --system >/dev/null 2>&1 || true
udevadm control --reload-rules >/dev/null 2>&1 || true
udevadm trigger --subsystem-match=block --action=change >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postinst"

cat > "$PKGROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/prerm"

mkdir -p "$ARTIFACTS"
dpkg-deb --build --root-owner-group "$PKGROOT" \
  "$ARTIFACTS/kernelnote-tuning_1.0.0_all.deb"
