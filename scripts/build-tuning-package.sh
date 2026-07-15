#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="$ROOT/artifacts"
PKGROOT="$ROOT/work/kernelnote-tuning"

rm -rf "$PKGROOT"
install -d "$PKGROOT/DEBIAN" \
           "$PKGROOT/etc/sysctl.d" \
           "$PKGROOT/etc/udev/rules.d" \
           "$PKGROOT/etc/default/grub.d" \
           "$PKGROOT/usr/lib/tmpfiles.d"

install -m 0644 "$ROOT/packaging/99-kernelnote.conf" \
  "$PKGROOT/etc/sysctl.d/99-kernelnote.conf"
install -m 0644 "$ROOT/packaging/65-kernelnote-adios.rules" \
  "$PKGROOT/etc/udev/rules.d/65-kernelnote-adios.rules"
install -m 0644 "$ROOT/packaging/99-kernelnote-grub.cfg" \
  "$PKGROOT/etc/default/grub.d/99-kernelnote.cfg"
install -m 0644 "$ROOT/packaging/99-kernelnote-thp.conf" \
  "$PKGROOT/usr/lib/tmpfiles.d/99-kernelnote-thp.conf"

cat > "$PKGROOT/DEBIAN/control" <<'EOF'
Package: kernelnote-tuning
Version: 1.1.0
Section: kernel
Priority: optional
Architecture: all
Maintainer: Kernelnote <noreply@localhost>
Depends: procps, udev, systemd | systemd-standalone-tmpfiles
Recommends: grub2-common
Description: Runtime and boot defaults for the Kernelnote Liquorix kernel
 Sets vm.swappiness=1, vm.page-cluster=0, selects ADIOS on every compatible
 block device, applies the requested Transparent Hugepage policy, and appends
 mitigations=off plus nowatchdog to GRUB without replacing existing arguments.
EOF

cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
sysctl --system >/dev/null 2>&1 || true
udevadm control --reload-rules >/dev/null 2>&1 || true
udevadm trigger --subsystem-match=block --action=change >/dev/null 2>&1 || true
systemd-tmpfiles --create /usr/lib/tmpfiles.d/99-kernelnote-thp.conf >/dev/null 2>&1 || true
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
if command -v update-grub >/dev/null 2>&1; then
  update-grub >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postrm"

mkdir -p "$ARTIFACTS"
dpkg-deb --build --root-owner-group "$PKGROOT" \
  "$ARTIFACTS/kernelnote-tuning_1.1.0_all.deb"
