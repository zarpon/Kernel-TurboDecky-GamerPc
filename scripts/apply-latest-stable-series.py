#!/usr/bin/env python3
"""Follow the resolved stable series for non-scheduler build rewrites."""

from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}"
        )
    return text.replace(old, new, 1)


def patch_core(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    replacements = {
        "linux-tkg-patches/7.1/": "linux-tkg-patches/${KERNEL_SERIES}/",
        "0007-v7.1-fsync1_via_futex_waitv.patch": "0007-v${KERNEL_SERIES}-fsync1_via_futex_waitv.patch",
        "genpatches/trunk/7.1/": "genpatches/trunk/${KERNEL_SERIES}/",
        "kernel-patches/refs/heads/master/7.1/": "kernel-patches/refs/heads/master/${KERNEL_SERIES}/",
        "Compatibility policy: Linux 7.1-specific or upstream-integrated source preferred":
            "Compatibility policy: Linux $KERNEL_SERIES-specific or upstream-integrated source preferred",
        "Compatibility policy: no usable Linux 7.1-specific source found; controlled port source selected":
            "Compatibility policy: no usable Linux $KERNEL_SERIES-specific source found; controlled port source selected",
        "Resolving requested patch series, preferring Linux 7.1 revisions":
            "Resolving requested patch series, preferring Linux $KERNEL_SERIES revisions",
        "already integrated in Linux 7.1.3 or an earlier patch":
            "already integrated in Linux $KERNEL_VERSION or an earlier patch",
        "if curl --fail --location --retry 3 --retry-all-errors --retry-delay 2 \\\n":
            "if curl --user-agent 'TurboDecky-GamerPc-CI/1.0 (+https://github.com/zarpon/Kernel-TurboDecky-GamerPc)' --fail --location \\\n        --retry 3 --retry-all-errors --retry-delay 2 \\\n",
        "if patch --batch --forward --strip=1 < \"$file\" > \"$LOGDIR/03-adios.apply.log\" 2>&1; then":
            "if patch --batch --forward --ignore-whitespace --strip=1 < \"$file\" > \"$LOGDIR/03-adios.apply.log\" 2>&1; then",
    }

    for old, new in replacements.items():
        if old not in source:
            raise SystemExit(f"latest-stable patch-series anchor missing: {old!r}")
        source = source.replace(old, new)

    source = replace_once(
        source,
        "scripts/config --disable LTO_CLANG_FULL\nscripts/config --enable LTO_CLANG_THIN\n",
        "scripts/config --disable LTO_CLANG_THIN\nscripts/config --enable LTO_CLANG_FULL\n",
        "Full LTO Kconfig selection",
    )
    source = replace_once(
        source,
        "assert_disabled_or_absent LTO_CLANG_FULL\n",
        "assert_disabled_or_absent LTO_CLANG_THIN\n",
        "Full LTO disabled-mode assertion",
    )
    source = replace_once(
        source,
        'assert_config "CONFIG_LTO_CLANG_THIN=y"\n',
        'assert_config "CONFIG_LTO_CLANG_FULL=y"\n',
        "Full LTO enabled-mode assertion",
    )

    thin_labels = source.count("ThinLTO")
    if thin_labels != 5:
        raise SystemExit(
            f"Full LTO policy: expected 5 ThinLTO labels in generated core, found {thin_labels}"
        )
    source = source.replace("ThinLTO", "Full LTO")

    thin_localversions = source.count("thinlto")
    if thin_localversions != 1:
        raise SystemExit(
            f"Full LTO policy: expected one thinlto localversion anchor, found {thin_localversions}"
        )
    source = source.replace("thinlto", "full-lto")

    path.write_text(source, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''  "cpuidle.governor=nap"
)
''',
        '''  "cpuidle.governor=nap"
  "kvm.enable_virt_at_load=0"
)
''',
        "VirtualBox/KVM command line",
    )
    source = replace_once(
        source,
        'scripts/config --enable CPU_IDLE_GOV_NAP\n',
        '''scripts/config --enable CPU_IDLE_GOV_NAP
# VirtualBox host drivers are external modules. Preserve the module loader,
# symbol metadata and host-network devices they require.
scripts/config --enable MODULES
scripts/config --enable MODULE_UNLOAD
scripts/config --enable MODULE_FORCE_UNLOAD
scripts/config --enable KALLSYMS
scripts/config --enable KALLSYMS_ALL
scripts/config --enable VIRTUALIZATION
scripts/config --module KVM
scripts/config --module KVM_INTEL
scripts/config --module KVM_AMD
scripts/config --module TUN
scripts/config --module BRIDGE
scripts/config --enable NETFILTER
''',
        "VirtualBox host Kconfig",
    )
    source = replace_once(
        source,
        'assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"\n',
        '''assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"
assert_config "CONFIG_MODULES=y"
assert_config "CONFIG_MODULE_UNLOAD=y"
assert_config "CONFIG_MODULE_FORCE_UNLOAD=y"
assert_config "CONFIG_KALLSYMS=y"
assert_config "CONFIG_KALLSYMS_ALL=y"
assert_config "CONFIG_VIRTUALIZATION=y"
assert_config "CONFIG_KVM=m"
assert_config "CONFIG_KVM_INTEL=m"
assert_config "CONFIG_KVM_AMD=m"
assert_config "CONFIG_TUN=m"
assert_config "CONFIG_BRIDGE=m"
assert_config "CONFIG_NETFILTER=y"
''',
        "VirtualBox host Kconfig assertions",
    )
    source = replace_once(
        source,
        'assert_cmdline_token "cpuidle.governor=nap"\n',
        '''assert_cmdline_token "cpuidle.governor=nap"
assert_cmdline_token "kvm.enable_virt_at_load=0"
''',
        "VirtualBox/KVM command-line assertion",
    )

    wrapper_thin_labels = source.count("ThinLTO")
    if wrapper_thin_labels not in (0, 2):
        raise SystemExit(
            f"Full LTO wrapper policy: expected 0 or 2 ThinLTO labels, found {wrapper_thin_labels}"
        )
    if wrapper_thin_labels:
        source = source.replace("ThinLTO", "Full LTO")

    wrapper_thin_localversions = source.count("thinlto")
    if wrapper_thin_localversions not in (0, 1):
        raise SystemExit(
            "Full LTO wrapper policy: expected 0 or 1 thinlto localversion anchors, "
            f"found {wrapper_thin_localversions}"
        )
    if wrapper_thin_localversions:
        source = source.replace("thinlto", "full-lto")

    path.write_text(source, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: apply-latest-stable-series.py <generated-core-script>"
        )

    core = Path(sys.argv[1])
    patch_core(core)
    patch_wrapper(core.with_name("build-kernelnote.sh"))


if __name__ == "__main__":
    main()
