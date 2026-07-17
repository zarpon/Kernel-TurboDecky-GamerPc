#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$ROOT/work"
LOGDIR="$ROOT/logs"
ARTIFACTS="$ROOT/artifacts"
SOURCE_DIR="$WORKDIR/dmemcg-booster"
PKGROOT="$WORKDIR/turbodecky-vram"

DMEMCG_BOOSTER_REPO="https://gitlab.steamos.cloud/holo/dmemcg-booster.git"
DMEMCG_BOOSTER_TAG="0.1.2"
PACKAGE_VERSION="0.1.2-1"

for command in git dpkg-deb pkg-config; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required VRAM package build tool is missing: $command" >&2
    exit 1
  }
done

if ! pkg-config --exists dbus-1 libdrm libsystemd; then
  command -v sudo >/dev/null 2>&1 || {
    echo "Missing dmemcg-booster development libraries and sudo is unavailable" >&2
    exit 1
  }
  sudo apt-get -o Acquire::Retries=3 update
  sudo apt-get install -y --no-install-recommends \
    libdbus-1-dev libdrm-dev libsystemd-dev pkg-config
fi

for command in cargo rustc; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required Rust tool is missing on the build runner: $command" >&2
    exit 1
  }
done

python3 - "$(rustc --version | awk '{print $2}')" <<'PYRUST'
import sys
version = tuple(int(part) for part in sys.argv[1].split('.')[:2])
if version < (1, 85):
    raise SystemExit(f"Rust 1.85 or newer is required for edition 2024; found {sys.argv[1]}")
PYRUST

rm -rf "$SOURCE_DIR" "$PKGROOT"
mkdir -p "$LOGDIR" "$ARTIFACTS"

echo "==> Fetching official Valve dmemcg-booster $DMEMCG_BOOSTER_TAG"
git init --quiet "$SOURCE_DIR"
git -C "$SOURCE_DIR" remote add origin "$DMEMCG_BOOSTER_REPO"
git -C "$SOURCE_DIR" fetch --no-tags --depth=1 origin \
  "refs/tags/$DMEMCG_BOOSTER_TAG:refs/tags/$DMEMCG_BOOSTER_TAG" \
  2>&1 | tee "$LOGDIR/08-dmemcg-booster-fetch.log"
git -C "$SOURCE_DIR" checkout --quiet --detach "$DMEMCG_BOOSTER_TAG"

actual_version="$(sed -n 's/^version = "\([^"]*\)"$/\1/p' "$SOURCE_DIR/Cargo.toml" | head -n1)"
[[ "$actual_version" == "$DMEMCG_BOOSTER_TAG" ]]
test -s "$SOURCE_DIR/Cargo.lock"
test -s "$SOURCE_DIR/dmemcg-booster-system.service"
test -s "$SOURCE_DIR/dmemcg-booster-user.service"

{
  echo "Component: Valve dmemcg-booster"
  echo "Repository: $DMEMCG_BOOSTER_REPO"
  echo "Tag: $DMEMCG_BOOSTER_TAG"
  echo "Commit: $(git -C "$SOURCE_DIR" rev-parse HEAD)"
  echo "Cargo.lock SHA256: $(sha256sum "$SOURCE_DIR/Cargo.lock" | awk '{print $1}')"
} | tee "$LOGDIR/08-dmemcg-booster-provenance.txt"

(
  cd "$SOURCE_DIR"
  cargo build --locked --release 2>&1 | tee "$LOGDIR/08-dmemcg-booster-build.log"
)
test -x "$SOURCE_DIR/target/release/dmemcg-booster"

install -d "$PKGROOT/DEBIAN" \
           "$PKGROOT/usr/bin" \
           "$PKGROOT/usr/lib/systemd/system" \
           "$PKGROOT/usr/lib/systemd/user" \
           "$PKGROOT/usr/lib/systemd/system-preset" \
           "$PKGROOT/usr/lib/systemd/user-preset" \
           "$PKGROOT/usr/share/doc/turbodecky-vram"

install -m 0755 "$SOURCE_DIR/target/release/dmemcg-booster" \
  "$PKGROOT/usr/bin/dmemcg-booster"
install -m 0644 "$SOURCE_DIR/dmemcg-booster-system.service" \
  "$PKGROOT/usr/lib/systemd/system/dmemcg-booster-system.service"
install -m 0644 "$SOURCE_DIR/dmemcg-booster-user.service" \
  "$PKGROOT/usr/lib/systemd/user/dmemcg-booster-user.service"

cat > "$PKGROOT/usr/lib/systemd/system-preset/90-turbodecky-vram.preset" <<'EOF'
enable dmemcg-booster-system.service
EOF
cat > "$PKGROOT/usr/lib/systemd/user-preset/90-turbodecky-vram.preset" <<'EOF'
enable dmemcg-booster-user.service
EOF

cat > "$PKGROOT/usr/bin/turbodecky-vram-status" <<'EOF'
#!/bin/sh
set -u

controllers=/sys/fs/cgroup/cgroup.controllers
printf '%s\n' 'TurboDecky VRAM/dmem status'
if [ -r "$controllers" ] && grep -qw dmem "$controllers"; then
  echo 'kernel dmem controller: available'
else
  echo 'kernel dmem controller: unavailable (boot the TurboDecky kernel)'
fi

if [ -r /sys/fs/cgroup/cgroup.subtree_control ] && \
   grep -qw dmem /sys/fs/cgroup/cgroup.subtree_control; then
  echo 'root dmem delegation: enabled'
else
  echo 'root dmem delegation: not enabled'
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl is-enabled dmemcg-booster-system.service 2>/dev/null \
    || echo 'system booster service: disabled'
  systemctl --global is-enabled dmemcg-booster-user.service 2>/dev/null \
    || echo 'user booster service: disabled'
fi

if command -v gamescope >/dev/null 2>&1; then
  echo 'gamescope: installed; launch games through gamescope for foreground VRAM protection'
else
  echo 'gamescope: not installed; install a build containing direct dmem.low support'
fi
EOF
chmod 0755 "$PKGROOT/usr/bin/turbodecky-vram-status"

cat > "$PKGROOT/usr/share/doc/turbodecky-vram/README.Debian" <<'EOF'
TurboDecky VRAM protection
==========================

The kernel TTM/dmem protection changes and dmemcg-booster services are enabled
by default. On non-KDE desktops, games should be launched through a Gamescope
build containing Valve commit 62b49b030cf76a0946292dd8379a87dcd16979ee or a
newer equivalent implementation. KDE Plasma can alternatively use
plasma-foreground-booster. Run turbodecky-vram-status after rebooting into the
TurboDecky kernel.
EOF

cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: turbodecky-vram
Version: $PACKAGE_VERSION
Section: kernel
Priority: optional
Architecture: amd64
Maintainer: TurboDecky GamerPc <noreply@localhost>
Depends: libc6, libdbus-1-3, libdrm2, libsystemd0, systemd
Recommends: gamescope
Description: Active device-memory cgroup support for TurboDecky gaming kernels
 Installs Valve dmemcg-booster, enables its system and global user services,
 and activates the userspace side required by the TTM/dmem VRAM protection
 patches. Gamescope or a desktop foreground booster marks the active game.
EOF

cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl preset dmemcg-booster-system.service >/dev/null 2>&1 || true
systemctl --global preset dmemcg-booster-user.service >/dev/null 2>&1 || true
systemctl enable dmemcg-booster-system.service >/dev/null 2>&1 || true
systemctl --global enable dmemcg-booster-user.service >/dev/null 2>&1 || true
if [ -r /sys/fs/cgroup/cgroup.controllers ] && \
   grep -qw dmem /sys/fs/cgroup/cgroup.controllers; then
  systemctl restart dmemcg-booster-system.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postinst"

cat > "$PKGROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = deconfigure ]; then
  systemctl disable --now dmemcg-booster-system.service >/dev/null 2>&1 || true
  systemctl --global disable dmemcg-booster-user.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/prerm"

cat > "$PKGROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postrm"

output="$ARTIFACTS/turbodecky-vram_${PACKAGE_VERSION}_amd64.deb"
dpkg-deb --build --root-owner-group "$PKGROOT" "$output"
dpkg-deb --info "$output" | tee "$LOGDIR/08-turbodecky-vram-package.txt"
dpkg-deb --contents "$output" | tee -a "$LOGDIR/08-turbodecky-vram-package.txt"
