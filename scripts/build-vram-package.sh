#!/usr/bin/env bash
set -Eeuo pipefail

MODE="${1:-validate}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="$ROOT/artifacts"
WORKDIR="$ROOT/work"
SRC="$WORKDIR/dmemcg-booster"
PKGROOT="$WORKDIR/turbodecky-vram"
VERSION="0.1.2"
PACKAGE_VERSION="${VERSION}-1turbodecky1"
PRIMARY_REPO="${DMEMCG_BOOSTER_REPO:-https://gitlab.steamos.cloud/holo/dmemcg-booster.git}"
PRIMARY_REF="${DMEMCG_BOOSTER_REF:-0.1.2}"
FALLBACK_REPO="${DMEMCG_BOOSTER_FALLBACK_REPO:-https://github.com/DistrictD64/dmemcg-booster.git}"
FALLBACK_COMMIT="${DMEMCG_BOOSTER_FALLBACK_COMMIT:-95162bdd9be9c4bd89d65cb558acb858c35f8bf6}"

case "$MODE" in
  validate|package) ;;
  *) echo "usage: $0 [validate|package]" >&2; exit 2 ;;
esac

install_build_dependencies() {
  if [[ -n "${DMEMCG_PREBUILT_BINARY:-}" ]]; then
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1 && [[ "${CI:-}" == "true" || "${TURBODECKY_INSTALL_BUILD_DEPS:-0}" == "1" ]]; then
    local -a privilege=()
    if ((EUID != 0)); then
      command -v sudo >/dev/null 2>&1 || {
        echo "sudo is required to install dmemcg-booster build dependencies" >&2
        return 1
      }
      privilege=(sudo)
    fi
    "${privilege[@]}" apt-get update
    "${privilege[@]}" apt-get install -y --no-install-recommends \
      ca-certificates cargo git libdbus-1-dev libdrm-dev pkg-config rustc
  fi
  command -v gcc >/dev/null 2>&1 || {
    echo "gcc is required for the audited C fallback" >&2
    return 1
  }
  command -v make >/dev/null 2>&1 || {
    echo "make is required for the audited C fallback" >&2
    return 1
  }
  pkg-config --exists dbus-1 || {
    echo "libdbus-1 development files are required" >&2
    return 1
  }
}

fetch_source() {
  rm -rf "$SRC"
  if git clone --depth 1 --branch "$PRIMARY_REF" --single-branch \
      "$PRIMARY_REPO" "$SRC"; then
    SOURCE_KIND="Valve/SteamOS upstream tag $PRIMARY_REF"
    SOURCE_REVISION="$(git -C "$SRC" rev-parse HEAD)"
    return 0
  fi

  echo "Primary dmemcg-booster source unavailable; using pinned audited GitHub fallback" >&2
  rm -rf "$SRC"
  git init --quiet "$SRC"
  git -C "$SRC" remote add origin "$FALLBACK_REPO"
  git -C "$SRC" fetch --no-tags --depth=1 origin "$FALLBACK_COMMIT"
  git -C "$SRC" checkout --detach FETCH_HEAD
  SOURCE_KIND="pinned audited C fallback"
  SOURCE_REVISION="$FALLBACK_COMMIT"
}

build_binary() {
  if [[ -n "${DMEMCG_PREBUILT_BINARY:-}" ]]; then
    test -x "$DMEMCG_PREBUILT_BINARY"
    BOOSTER_BINARY="$DMEMCG_PREBUILT_BINARY"
    SOURCE_KIND="local prebuilt validation input"
    SOURCE_REVISION="not-applicable"
    return 0
  fi

  fetch_source
  if [[ -f "$SRC/Cargo.toml" ]]; then
    command -v cargo >/dev/null 2>&1 || {
      echo "cargo is required to build Valve dmemcg-booster 0.1.2" >&2
      return 1
    }
    command -v rustc >/dev/null 2>&1 || {
      echo "rustc is required to build Valve dmemcg-booster 0.1.2" >&2
      return 1
    }
    if command -v rustup >/dev/null 2>&1; then
      rustup toolchain install stable --profile minimal --no-self-update
      rustup default stable
    fi
    grep -Fq 'name = "dmemcg-booster"' "$SRC/Cargo.toml"
    grep -Fq 'version = "0.1.2"' "$SRC/Cargo.toml"
    (
      cd "$SRC"
      cargo build --locked --release
    )
    BOOSTER_BINARY="$SRC/target/release/dmemcg-booster"
  elif [[ -f "$SRC/Makefile" && -f "$SRC/src/main.c" ]]; then
    grep -Fq -- '--use-system-bus' "$SRC/src/main.c"
    make -C "$SRC" clean all
    BOOSTER_BINARY="$SRC/dmemcg-booster"
  else
    echo "unrecognized dmemcg-booster source layout" >&2
    return 1
  fi
  test -x "$BOOSTER_BINARY"
}

install_build_dependencies
build_binary

rm -rf "$PKGROOT"
install -d "$PKGROOT/DEBIAN" \
  "$PKGROOT/usr/bin" \
  "$PKGROOT/usr/lib/systemd/system" \
  "$PKGROOT/usr/lib/systemd/user" \
  "$PKGROOT/usr/lib/systemd/system/user@.service.d" \
  "$PKGROOT/usr/share/doc/turbodecky-vram" \
  "$PKGROOT/etc/systemd/system/multi-user.target.wants" \
  "$PKGROOT/etc/systemd/user/default.target.wants"

install -m 0755 "$BOOSTER_BINARY" "$PKGROOT/usr/bin/dmemcg-booster"

cat > "$PKGROOT/usr/bin/turbodecky-vram-run" <<'EOF'
#!/bin/sh
set -eu
if [ "$#" -eq 0 ]; then
  echo "Uso: turbodecky-vram-run comando [argumentos...]" >&2
  exit 2
fi
unit="turbodecky-vram-$PPID-$$"
exec systemd-run --user --scope --collect --quiet --unit="$unit" -- "$@"
EOF
chmod 0755 "$PKGROOT/usr/bin/turbodecky-vram-run"

cat > "$PKGROOT/usr/lib/systemd/system/dmemcg-booster-system.service" <<'EOF'
[Unit]
Description=Enable and propagate the device-memory cgroup controller
Documentation=https://pixelcluster.dev/VRAM-Mgmt-fixed/
After=dbus.service systemd-remount-fs.service
ConditionPathExists=/sys/fs/cgroup/cgroup.controllers

[Service]
Type=simple
ExecStart=/usr/bin/dmemcg-booster --use-system-bus
Restart=on-failure
RestartSec=2s
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/sys/fs/cgroup

[Install]
WantedBy=multi-user.target
EOF

cat > "$PKGROOT/usr/lib/systemd/user/dmemcg-booster-user.service" <<'EOF'
[Unit]
Description=Enable device-memory controls in the user cgroup hierarchy
Documentation=https://pixelcluster.dev/VRAM-Mgmt-fixed/
After=dbus.service
ConditionPathExists=/sys/fs/cgroup/cgroup.controllers

[Service]
Type=simple
ExecStart=/usr/bin/dmemcg-booster
Restart=on-failure
RestartSec=2s
NoNewPrivileges=yes

[Install]
WantedBy=default.target
EOF

cat > "$PKGROOT/usr/lib/systemd/system/user@.service.d/90-turbodecky-dmem.conf" <<'EOF'
[Service]
Delegate=yes
EOF

ln -s /usr/lib/systemd/system/dmemcg-booster-system.service \
  "$PKGROOT/etc/systemd/system/multi-user.target.wants/dmemcg-booster-system.service"
ln -s /usr/lib/systemd/user/dmemcg-booster-user.service \
  "$PKGROOT/etc/systemd/user/default.target.wants/dmemcg-booster-user.service"

cat > "$PKGROOT/usr/share/doc/turbodecky-vram/README.Debian" <<EOF
TurboDecky VRAM management
==========================

The kernel side requires CONFIG_CGROUP_DMEM=y and the TurboDecky TTM/DMEM patch.
The system and user dmemcg-booster services are enabled by default.

For generic desktops, launch a game with:

  turbodecky-vram-run <game command>

Steam launch option:

  turbodecky-vram-run %command%

Recent gamescope versions can provide foreground-game integration directly.
KDE Plasma users may alternatively install plasma-foreground-booster-dmemcg.

Source: $SOURCE_KIND
Revision: $SOURCE_REVISION
EOF

cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: turbodecky-vram
Version: $PACKAGE_VERSION
Section: utils
Priority: optional
Architecture: amd64
Maintainer: TurboDecky GamerPc <noreply@localhost>
Depends: libc6, libdbus-1-3, libdrm2, systemd, dbus-user-session
Recommends: gamescope
Description: Cgroup-aware VRAM management for the TurboDecky kernel
 Installs Valve's dmemcg-booster, enables its system and user services,
 delegates the user cgroup hierarchy, and provides a generic systemd-scope
 launcher for foreground games.
EOF

cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl enable dmemcg-booster-system.service >/dev/null 2>&1 || true
  systemctl restart dmemcg-booster-system.service >/dev/null 2>&1 || true
  systemctl --user --global enable dmemcg-booster-user.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postinst"

cat > "$PKGROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] && command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now dmemcg-booster-system.service >/dev/null 2>&1 || true
  systemctl --user --global disable dmemcg-booster-user.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/prerm"

cat > "$PKGROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$PKGROOT/DEBIAN/postrm"

mkdir -p "$ARTIFACTS"
OUTPUT="$ARTIFACTS/turbodecky-vram_${PACKAGE_VERSION}_amd64.deb"
dpkg-deb --build --root-owner-group "$PKGROOT" "$OUTPUT"
dpkg-deb --info "$OUTPUT"
dpkg-deb --contents "$OUTPUT" > "$WORKDIR/turbodecky-vram-contents.txt"
grep -Fq './usr/bin/dmemcg-booster' "$WORKDIR/turbodecky-vram-contents.txt"
grep -Fq './usr/bin/turbodecky-vram-run' "$WORKDIR/turbodecky-vram-contents.txt"
grep -Fq 'dmemcg-booster-system.service' "$WORKDIR/turbodecky-vram-contents.txt"
grep -Fq 'dmemcg-booster-user.service' "$WORKDIR/turbodecky-vram-contents.txt"
sha256sum "$OUTPUT"
