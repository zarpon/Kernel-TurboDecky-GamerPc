#!/usr/bin/env python3
"""Switch the generated build from Liquorix to kernel.org latest stable Linux."""

from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-upstream-generic.py <build-kernelnote-core.sh>")

    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        'KERNEL_TAG="v7.1.3-lqx1"\n',
        ''': "${KERNEL_VERSION:?latest stable version was not resolved}"
: "${KERNEL_SERIES:?latest stable series was not resolved}"
: "${KERNEL_TAG:?latest stable tag was not resolved}"
: "${KERNEL_DEB_VERSION:?Debian package version was not resolved}"
''',
        "dynamic upstream tag",
    )
    source = replace_once(
        source,
        'KERNEL_REPO="https://github.com/zen-kernel/zen-kernel.git"\n',
        'KERNEL_REPO="https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"\n',
        "upstream repository",
    )
    source = replace_once(
        source,
        'echo "==> Cloning official Liquorix source tag $KERNEL_TAG"\n',
        'echo "==> Cloning kernel.org latest stable source tag $KERNEL_TAG"\n',
        "clone description",
    )
    source = replace_once(
        source,
        'git clone --depth 1 --single-branch --no-tags --branch "$KERNEL_TAG" "$KERNEL_REPO" "$KERNELDIR"\n',
        '''git clone --depth 1 --single-branch --no-tags --branch "$KERNEL_TAG" "$KERNEL_REPO" "$KERNELDIR"
actual_kernel_version="$(make -s -C "$KERNELDIR" kernelversion)"
if [[ "$actual_kernel_version" != "$KERNEL_VERSION" ]]; then
  echo "Cloned kernel version mismatch: $actual_kernel_version != $KERNEL_VERSION" >&2
  exit 1
fi
{
  echo "Policy: kernel.org latest_stable"
  echo "Resolved version: $KERNEL_VERSION"
  echo "Resolved series: $KERNEL_SERIES"
  echo "Source tag: $KERNEL_TAG"
  echo "Repository: $KERNEL_REPO"
  echo "Source URL: ${KERNEL_SOURCE_URL:-unknown}"
  echo "Release date: ${KERNEL_RELEASE_DATE:-unknown}"
} | tee "$LOGDIR/kernel-source-policy.txt"
''',
        "source version verification",
    )

    whitespace_anchor = '''    path.write_text("".join(output), encoding="utf-8")
PY
}
'''
    whitespace_block = '''    # Preserve exactly one final newline while removing extra blank lines at EOF.
    normalized = "".join(output).rstrip("\\n") + "\\n"
    path.write_text(normalized, encoding="utf-8")
PY
}
'''
    source = replace_once(
        source,
        whitespace_anchor,
        whitespace_block,
        "patched-file whitespace normalization",
    )

    config_anchor = 'cp "$WORKDIR/liquorix-amd64.config" .config\n'
    config_block = config_anchor + r'''
# Fixed target: HP 240 G4 with Intel Core i3-5005U (Broadwell-U),
# two physical cores, four threads, one socket and no NUMA topology.
# Keep the established performance configuration baseline, then remove CPU
# families and platforms that cannot exist on the target notebook.
scripts/config --enable 64BIT
scripts/config --enable X86_64
scripts/config --enable SMP
scripts/config --set-val NR_CPUS 4
# CPU vendor symbols default to y and are only user-selectable when the
# PROCESSOR_SELECT menu is enabled. Make the menu explicit before disabling
# non-Intel vendors, otherwise olddefconfig silently restores their defaults.
scripts/config --enable EXPERT
scripts/config --enable PROCESSOR_SELECT
scripts/config --enable CPU_SUP_INTEL
scripts/config --disable CPU_SUP_AMD
scripts/config --disable CPU_SUP_HYGON
scripts/config --disable CPU_SUP_CENTAUR
scripts/config --disable CPU_SUP_ZHAOXIN
# Since Linux 7.1 the x86 microcode Kconfig is unified. CONFIG_MICROCODE is a
# def_bool selected by the enabled CPU vendor; there are no MICROCODE_INTEL or
# MICROCODE_AMD symbols. With CPU_SUP_INTEL=y and CPU_SUP_AMD=n this compiles
# only the Intel loader path required by the Broadwell notebook.
scripts/config --enable MICROCODE
scripts/config --enable X86_MCE
scripts/config --enable X86_MCE_INTEL
scripts/config --disable X86_MCE_AMD
scripts/config --disable NUMA
scripts/config --disable X86_5LEVEL
scripts/config --disable MAXSMP
scripts/config --disable X86_NATIVE_CPU
scripts/config --disable X86_VSMP
scripts/config --disable X86_UV
scripts/config --disable X86_GOLDFISH
scripts/config --disable X86_INTEL_MID

# Fixed-notebook media profile. Preserve only the V4L2 path needed by the HP
# 240 G4 USB UVC webcam. Do not compile external broadcast/capture hardware:
# analog TV, DVB, radio, SDR, PCI/platform capture, camera sensor farms, legacy
# USB webcam families, infrared remotes or synthetic media test devices.
scripts/config --module MEDIA_SUPPORT
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
scripts/config --disable MEDIA_TEST_SUPPORT
scripts/config --disable VIDEO_CAMERA_SENSOR
scripts/config --disable USB_GSPCA
scripts/config --disable USB_PWC
scripts/config --disable VIDEO_S2255
scripts/config --disable VIDEO_USBTV
scripts/config --disable VIDEO_EM28XX
scripts/config --disable MEDIA_CEC_RC
scripts/config --disable RC_CORE
scripts/config --disable RC_MAP
scripts/config --disable RC_DECODERS
scripts/config --disable RC_DEVICES
'''
    source = replace_once(source, config_anchor, config_block, "Broadwell and media profile")

    assertion_anchor = 'assert_config "CONFIG_CPU_MITIGATIONS=y"\n'
    assertion_block = r'''assert_config "CONFIG_64BIT=y"
assert_config "CONFIG_X86_64=y"
assert_config "CONFIG_SMP=y"
assert_config "CONFIG_NR_CPUS=4"
assert_config "CONFIG_EXPERT=y"
assert_config "CONFIG_PROCESSOR_SELECT=y"
assert_config "CONFIG_CPU_SUP_INTEL=y"
assert_config "CONFIG_MICROCODE=y"
assert_config "CONFIG_X86_MCE=y"
assert_config "CONFIG_X86_MCE_INTEL=y"
assert_disabled_or_absent CPU_SUP_AMD
assert_disabled_or_absent CPU_SUP_HYGON
assert_disabled_or_absent CPU_SUP_CENTAUR
assert_disabled_or_absent CPU_SUP_ZHAOXIN
assert_disabled_or_absent X86_MCE_AMD
assert_disabled_or_absent NUMA
assert_disabled_or_absent X86_5LEVEL
assert_disabled_or_absent MAXSMP
assert_disabled_or_absent X86_NATIVE_CPU
assert_disabled_or_absent X86_VSMP
assert_disabled_or_absent X86_UV
assert_disabled_or_absent X86_GOLDFISH
assert_disabled_or_absent X86_INTEL_MID
assert_config "CONFIG_MEDIA_SUPPORT=m"
assert_config "CONFIG_MEDIA_SUPPORT_FILTER=y"
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
assert_disabled_or_absent MEDIA_TEST_SUPPORT
assert_disabled_or_absent VIDEO_CAMERA_SENSOR
assert_disabled_or_absent USB_GSPCA
assert_disabled_or_absent USB_PWC
assert_disabled_or_absent VIDEO_S2255
assert_disabled_or_absent VIDEO_USBTV
assert_disabled_or_absent VIDEO_EM28XX
assert_disabled_or_absent MEDIA_CEC_RC
assert_disabled_or_absent RC_CORE
assert_disabled_or_absent RC_MAP
assert_disabled_or_absent RC_DECODERS
assert_disabled_or_absent RC_DEVICES
assert_config "CONFIG_CPU_MITIGATIONS=y"
'''
    source = replace_once(source, assertion_anchor, assertion_block, "Broadwell and media assertions")

    source = replace_once(
        source,
        'cp .config "$LOGDIR/final.config"\n',
        '''{
  echo "Target: HP 240 G4 notebook"
  echo "Preserved: V4L2 core, media controller and USB UVC webcam"
  echo "Disabled: TV/DVB/radio/SDR, PCI/platform capture, sensor farm, legacy USB webcams, media tests and IR remotes"
  echo "Reason: avoid compiling external media hardware that cannot exist in the fixed notebook target"
} | tee "$LOGDIR/media-profile.txt"

cp .config "$LOGDIR/final.config"
''',
        "media profile provenance",
    )

    source = source.replace(
        'KDEB_PKGVERSION="7.1.3-1kernelnote1"',
        'KDEB_PKGVERSION="$KERNEL_DEB_VERSION"',
    )
    source = source.replace(
        'echo "==> Kernelnote ThinLTO build completed successfully"',
        'echo "==> Latest-stable upstream Zarpon ThinLTO build completed successfully"',
    )

    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
