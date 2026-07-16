#!/usr/bin/env python3
"""Force the exact TurboLQX UTS release while keeping Debian package names valid."""

from __future__ import annotations

import sys
from pathlib import Path

KERNEL_RELEASE = "Linux7.1.3.TurboLQX.lqx1"
PACKAGE_RELEASE = KERNEL_RELEASE.lower()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}"
        )
    return text.replace(old, new, 1)


def patch_core(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        'MAKE=(make LLVM=1 LLVM_IAS=1)\n',
        f'''KERNEL_RELEASE_NAME="{KERNEL_RELEASE}"
# KERNELRELEASE is passed as a make command-line variable so uname -r,
# module paths, vermagic, installed image names and package metadata all use
# the exact requested identifier, independently of Liquorix EXTRAVERSION.
MAKE=(make LLVM=1 LLVM_IAS=1 KERNELRELEASE="$KERNEL_RELEASE_NAME")
''',
        "exact KERNELRELEASE",
    )

    source = replace_once(
        source,
        'normalize_changed_whitespace() {\n',
        rf'''configure_kernelzarpon_debian_packaging() {{
  echo "==> Configuring exact {KERNEL_RELEASE} release and Debian-safe package names"
  python3 - <<'PY'
from pathlib import Path

mkdebian = Path("scripts/package/mkdebian")
text = mkdebian.read_text(encoding="utf-8")

anchor = "packagename=linux-image\nfi\n"
if text.count(anchor) != 1:
    raise SystemExit("mkdebian package-name anchor not found exactly once")
text = text.replace(
    anchor,
    anchor
    + "\n# Debian binary package names must be lowercase even when the kernel's\n"
    + "# UTS release intentionally contains branding capitals.\n"
    + "packagerelease=$(printf '%s' \"$KERNELRELEASE\" | tr '[:upper:]' '[:lower:]')\n",
    1,
)

replacements = {{
    "Package: $packagename-${{KERNELRELEASE}}":
        "Package: $packagename-${{packagerelease}}",
    "Package: linux-headers-${{KERNELRELEASE}}":
        "Package: linux-headers-${{packagerelease}}",
    "Package: linux-image-${{KERNELRELEASE}}-dbg":
        "Package: linux-image-${{packagerelease}}-dbg",
}}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"mkdebian expected one occurrence of {{old!r}}")
    text = text.replace(old, new, 1)

mkdebian.write_text(text, encoding="utf-8")

builddeb = Path("scripts/package/builddeb")
text = builddeb.read_text(encoding="utf-8")
old = "version=${{1#linux-headers-}}"
new = "version=${{KERNELRELEASE}}"
if text.count(old) != 1:
    raise SystemExit("builddeb header-version anchor not found exactly once")
text = text.replace(old, new, 1)
builddeb.write_text(text, encoding="utf-8")
PY

  {{
    echo "Kernel UTS release: $KERNEL_RELEASE_NAME"
    echo "Debian package release: {PACKAGE_RELEASE}"
    echo "Image package: linux-image-{PACKAGE_RELEASE}"
    echo "Headers package: linux-headers-{PACKAGE_RELEASE}"
    echo "Reason: Debian package names permit only lowercase ASCII letters."
  }} | tee "$LOGDIR/kernel-name-policy.txt"

  git diff --check -- scripts/package/mkdebian scripts/package/builddeb \
    | tee "$LOGDIR/08-kernelzarpon-package-diff-check.log"
  grep -Fq 'packagerelease=' scripts/package/mkdebian
  grep -Fq 'version=${{KERNELRELEASE}}' scripts/package/builddeb
  echo "==> TurboLQX naming policy configured successfully"
}}

normalize_changed_whitespace() {{
''',
        "TurboLQX packaging function",
    )

    source = replace_once(
        source,
        'apply_reflex_patch "$REFLEX_PATCH"\n\ncp "$WORKDIR/liquorix-amd64.config" .config\n',
        '''apply_reflex_patch "$REFLEX_PATCH"
configure_kernelzarpon_debian_packaging

cp "$WORKDIR/liquorix-amd64.config" .config
''',
        "TurboLQX packaging call",
    )

    source = replace_once(
        source,
        '''# BORE enhances the normal CFS/EEVDF path. Liquorix PDS/BMQ must be disabled,
''',
        '''# Fixed-notebook media profile. The HP 240 G4 webcam is a USB UVC device,
# so retain V4L2, the media controller and USB_VIDEO_CLASS. The generic Liquorix
# configuration also builds hundreds of analog-TV, DVB, SDR, radio, PCI capture,
# camera-sensor and infrared-remote modules. Those are external peripherals, not
# notebook hardware, and were still compiling when the hosted six-hour limit was
# reached. Remove only those families while preserving normal webcams and CEC.
scripts/config --enable MEDIA_SUPPORT
scripts/config --enable MEDIA_SUPPORT_FILTER
scripts/config --disable MEDIA_SUBDRV_AUTOSELECT
scripts/config --enable MEDIA_CAMERA_SUPPORT
scripts/config --enable MEDIA_USB_SUPPORT
scripts/config --module VIDEO_DEV
scripts/config --module USB_VIDEO_CLASS
scripts/config --enable MEDIA_CONTROLLER
scripts/config --disable MEDIA_ANALOG_TV_SUPPORT
scripts/config --disable MEDIA_DIGITAL_TV_SUPPORT
scripts/config --disable MEDIA_RADIO_SUPPORT
scripts/config --disable MEDIA_SDR_SUPPORT
scripts/config --disable MEDIA_PLATFORM_SUPPORT
scripts/config --disable MEDIA_PCI_SUPPORT
scripts/config --disable VIDEO_CAMERA_SENSOR
scripts/config --disable MEDIA_CEC_RC
scripts/config --disable RC_CORE
scripts/config --disable RC_MAP
scripts/config --disable RC_DECODERS
scripts/config --disable RC_DEVICES

# BORE enhances the normal CFS/EEVDF path. Liquorix PDS/BMQ must be disabled,
''',
        "HP 240 G4 media profile",
    )

    source = replace_once(
        source,
        '''# BORE enhances the normal CFS/EEVDF path. Liquorix PDS/BMQ must be disabled,
''',
        '''source "$ROOT/scripts/notebook-prune-profile.sh"
apply_notebook_prune_profile

# BORE enhances the normal CFS/EEVDF path. Liquorix PDS/BMQ must be disabled,
''',
        "shared notebook pruning apply call",
    )

    source = replace_once(
        source,
        'assert_config "CONFIG_CPU_MITIGATIONS=y"\n',
        '''assert_config "CONFIG_MEDIA_SUPPORT=m"
assert_config "CONFIG_MEDIA_CAMERA_SUPPORT=y"
assert_config "CONFIG_MEDIA_USB_SUPPORT=y"
assert_config "CONFIG_VIDEO_DEV=m"
assert_config "CONFIG_USB_VIDEO_CLASS=m"
assert_config "CONFIG_MEDIA_CONTROLLER=y"
assert_disabled_or_absent MEDIA_SUBDRV_AUTOSELECT
assert_disabled_or_absent MEDIA_ANALOG_TV_SUPPORT
assert_disabled_or_absent MEDIA_DIGITAL_TV_SUPPORT
assert_disabled_or_absent MEDIA_RADIO_SUPPORT
assert_disabled_or_absent MEDIA_SDR_SUPPORT
assert_disabled_or_absent MEDIA_PLATFORM_SUPPORT
assert_disabled_or_absent MEDIA_PCI_SUPPORT
assert_disabled_or_absent VIDEO_CAMERA_SENSOR
assert_disabled_or_absent MEDIA_CEC_RC
assert_disabled_or_absent RC_CORE
assert_disabled_or_absent RC_MAP
assert_disabled_or_absent RC_DECODERS
assert_disabled_or_absent RC_DEVICES
assert_config "CONFIG_CPU_MITIGATIONS=y"
''',
        "HP 240 G4 media assertions",
    )

    source = replace_once(
        source,
        'assert_config "CONFIG_CPU_MITIGATIONS=y"\n',
        '''verify_notebook_prune_profile
assert_config "CONFIG_CPU_MITIGATIONS=y"
''',
        "shared notebook pruning verification call",
    )

    source = replace_once(
        source,
        'cp .config "$LOGDIR/final.config"\n',
        '''{
  echo "Target: HP 240 G4 notebook"
  echo "Preserved: V4L2 media core, media controller, USB UVC webcam"
  echo "Disabled: analog TV, DVB, radio, SDR, media PCI/platform capture, sensor farm, IR remotes"
  echo "Reason: remove external broadcast/capture modules that exhausted the hosted build window"
} | tee "$LOGDIR/media-profile.txt"

cp .config "$LOGDIR/final.config"
''',
        "media profile provenance",
    )

    source = replace_once(
        source,
        'cp .config "$LOGDIR/final.config"\n',
        '''write_notebook_prune_profile
cp .config "$LOGDIR/final.config"
''',
        "shared notebook pruning log call",
    )

    path.write_text(source, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    old_local = '-kn-marie-bore-poc-nap-rfx-adios-zir-lto'
    if source.count(old_local) != 1:
        raise SystemExit(
            f"TurboLQX localversion: expected one {old_local!r} occurrence"
        )
    source = source.replace(old_local, "", 1)

    emitted = '''kernel_release="$(${MAKE[@]} -s kernelrelease)"
printf '%s\\n' "$kernel_release" | tee "$LOGDIR/kernelrelease.txt"
if ((${#kernel_release} > 64)); then
  echo "Kernel release exceeds the 64-character UTS_RELEASE limit: ${#kernel_release}" >&2
  exit 1
fi
'''
    # Preserve the exact original command spelling generated by build-kernelnote.sh.
    emitted = emitted.replace('$(${MAKE[@]} -s kernelrelease)', '$("${MAKE[@]}" -s kernelrelease)')
    replacement = emitted + '''if [[ "$kernel_release" != "$KERNEL_RELEASE_NAME" ]]; then
  echo "Unexpected kernel release: $kernel_release (expected $KERNEL_RELEASE_NAME)" >&2
  exit 1
fi
'''
    if source.count(emitted) != 1:
        raise SystemExit("TurboLQX kernelrelease validation block not found exactly once")
    source = source.replace(emitted, replacement, 1)

    path.write_text(source, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: apply-kernelzarpon-name.py <build-kernelnote-core.sh> "
            "<build-kernelnote.sh>"
        )
    patch_core(Path(sys.argv[1]))
    patch_wrapper(Path(sys.argv[2]))


if __name__ == "__main__":
    main()
