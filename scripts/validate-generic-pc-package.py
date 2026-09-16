#!/usr/bin/env python3
"""Fail a TurboDecky package build if generic-PC hardware coverage collapses."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

MIN_CONFIG_MODULES = 5000
MIN_PACKAGED_MODULES = 5000
MIN_IMAGE_BYTES = 64 * 1024 * 1024

REQUIRED = {
    "CONFIG_MODULES": {"y"},
    "CONFIG_DRM_AMDGPU": {"m"},
    "CONFIG_DRM_I915": {"m"},
    "CONFIG_DRM_NOUVEAU": {"m"},
    "CONFIG_BLK_DEV_NVME": {"y", "m"},
    "CONFIG_SATA_AHCI": {"y", "m"},
    "CONFIG_BT": {"m"},
    "CONFIG_CFG80211": {"m"},
    "CONFIG_MAC80211": {"m"},
    "CONFIG_E1000E": {"m"},
    "CONFIG_IGB": {"m"},
    "CONFIG_IGC": {"m"},
    "CONFIG_R8169": {"m"},
    "CONFIG_USB_XHCI_HCD": {"y", "m"},
    "CONFIG_USB_STORAGE": {"m"},
    "CONFIG_SND_HDA_INTEL": {"m"},
    "CONFIG_SND_SOC": {"m"},
    "CONFIG_EXT4_FS": {"y", "m"},
    "CONFIG_XFS_FS": {"y", "m"},
    "CONFIG_BTRFS_FS": {"y", "m"},
    "CONFIG_F2FS_FS": {"m"},
    "CONFIG_NTFS3_FS": {"m"},
    "CONFIG_KVM": {"m"},
    "CONFIG_KVM_INTEL": {"m"},
    "CONFIG_KVM_AMD": {"m"},
    "CONFIG_TUN": {"m"},
    "CONFIG_BRIDGE": {"m"},
}


def parse_config(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            cfg[key] = value
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            cfg[line[2:-11]] = "n"
    return cfg


def fail(message: str) -> None:
    raise SystemExit(f"generic PC coverage regression: {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--modules-order", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    cfg = parse_config(args.config)
    module_symbols = sum(value == "m" for value in cfg.values())
    if module_symbols < MIN_CONFIG_MODULES:
        fail(f"only {module_symbols} CONFIG_*=m symbols; expected at least {MIN_CONFIG_MODULES}")

    bad = []
    for key, allowed in REQUIRED.items():
        value = cfg.get(key, "n")
        if value not in allowed:
            bad.append(f"{key}={value} (expected {'/'.join(sorted(allowed))})")
    if bad:
        fail("required hardware options missing: " + ", ".join(bad))

    ordered = [line.strip() for line in args.modules_order.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if len(ordered) < MIN_PACKAGED_MODULES:
        fail(f"modules.order has only {len(ordered)} entries; expected at least {MIN_PACKAGED_MODULES}")

    images = sorted(args.artifacts.glob("linux-image-*.deb"))
    if len(images) != 1:
        fail(f"expected exactly one linux-image package, found {len(images)}")
    image = images[0]
    if image.stat().st_size < MIN_IMAGE_BYTES:
        fail(f"{image.name} is only {image.stat().st_size} bytes; floor is {MIN_IMAGE_BYTES}")

    listing = subprocess.run(
        ["dpkg-deb", "--contents", str(image)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.splitlines()
    names = [line.split(maxsplit=5)[-1] for line in listing if line.strip()]
    packaged_modules = [
        name for name in names
        if re.search(r"(?:^|/)lib/modules/.+\.ko(?:\.(?:xz|zst|gz))?$", name)
    ]
    if len(packaged_modules) < MIN_PACKAGED_MODULES:
        fail(f"linux-image contains only {len(packaged_modules)} kernel modules; expected at least {MIN_PACKAGED_MODULES}")

    for pattern in (r"(?:^|/)boot/vmlinuz-", r"(?:^|/)boot/config-", r"(?:^|/)boot/System\.map-"):
        if not any(re.search(pattern, name) for name in names):
            fail(f"linux-image is missing package payload matching {pattern}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = (
        "TurboDecky generic PC coverage: PASS\n"
        f"CONFIG_*=m symbols: {module_symbols}\n"
        f"modules.order entries: {len(ordered)}\n"
        f"packaged modules: {len(packaged_modules)}\n"
        f"linux-image bytes: {image.stat().st_size}\n"
        f"linux-image: {image.name}\n"
    )
    args.report.write_text(report, encoding="utf-8")
    print(report, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
