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
scripts/config --enable CPU_SUP_INTEL
scripts/config --disable CPU_SUP_AMD
scripts/config --disable CPU_SUP_HYGON
scripts/config --disable CPU_SUP_CENTAUR
scripts/config --disable CPU_SUP_ZHAOXIN
scripts/config --enable MICROCODE
scripts/config --enable MICROCODE_INTEL
scripts/config --disable MICROCODE_AMD
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
'''
    source = replace_once(source, config_anchor, config_block, "Broadwell profile")

    assertion_anchor = 'assert_config "CONFIG_CPU_MITIGATIONS=y"\n'
    assertion_block = r'''assert_config "CONFIG_64BIT=y"
assert_config "CONFIG_X86_64=y"
assert_config "CONFIG_SMP=y"
assert_config "CONFIG_NR_CPUS=4"
assert_config "CONFIG_CPU_SUP_INTEL=y"
assert_config "CONFIG_MICROCODE=y"
assert_config "CONFIG_MICROCODE_INTEL=y"
assert_config "CONFIG_X86_MCE=y"
assert_config "CONFIG_X86_MCE_INTEL=y"
assert_disabled_or_absent CPU_SUP_AMD
assert_disabled_or_absent CPU_SUP_HYGON
assert_disabled_or_absent CPU_SUP_CENTAUR
assert_disabled_or_absent CPU_SUP_ZHAOXIN
assert_disabled_or_absent MICROCODE_AMD
assert_disabled_or_absent X86_MCE_AMD
assert_disabled_or_absent NUMA
assert_disabled_or_absent X86_5LEVEL
assert_disabled_or_absent MAXSMP
assert_disabled_or_absent X86_NATIVE_CPU
assert_disabled_or_absent X86_VSMP
assert_disabled_or_absent X86_UV
assert_disabled_or_absent X86_GOLDFISH
assert_disabled_or_absent X86_INTEL_MID
assert_config "CONFIG_CPU_MITIGATIONS=y"
'''
    source = replace_once(source, assertion_anchor, assertion_block, "Broadwell assertions")

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
