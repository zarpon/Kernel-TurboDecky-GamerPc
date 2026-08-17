#!/usr/bin/env python3
"""Finish the graysky CPU-optimization Kconfig hunk on Linux 7.2.

The 6.16+ patch still carries a dependency for X86_TSC that Linux 7.2 removed
upstream. GNU patch therefore rejects the combined Kconfig hunk after the other
CPU-selection hunks have applied. This adapter is deliberately narrow: it
accepts only that known reject, updates the still-relevant dependency lists,
and preserves Linux 7.2's unconditional X86_TSC semantics.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


class PortError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PortError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def validate_reject(reject: str) -> None:
    required = (
        "config X86_INTEL_USERCOPY",
        "config X86_USE_PPRO_CHECKSUM",
        "config X86_TSC",
        "config X86_HAVE_PAE",
        '-\tdepends on MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M586MMX || X86_GENERIC || MK7 || MEFFICEON',
        '-\tdepends on MWINCHIP3D || MWINCHIPC6 || MCYRIXIII || MK7 || MK6 || MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M686 || MVIAC3_2 || MVIAC7 || MEFFICEON || MGEODE_LX || MATOM',
        '-\tdepends on (MWINCHIP3D || MCRUSOE || MEFFICEON || MCYRIXIII || MK7 || MK6 || MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M686 || M586MMX || M586TSC || MVIAC3_2 || MVIAC7 || MGEODEGX1 || MGEODE_LX || MATOM) || X86_64',
        '-\tdepends on MCRUSOE || MEFFICEON || MCYRIXIII || MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M686 || MVIAC7 || MATOM || X86_64',
    )
    missing = [marker for marker in required if marker not in reject]
    if missing:
        raise PortError(f"unexpected CPU optimization reject; missing markers: {missing}")
    if reject.count("@@") != 2:
        raise PortError("CPU optimization reject must contain exactly one hunk")


def port_kconfig(path: Path, reject_path: Path, kernel_version: str) -> None:
    if not re.fullmatch(r"7\.2(?:\.\d+)?", kernel_version):
        raise PortError(f"unsupported kernel for CPU optimization adapter: {kernel_version}")
    if not path.is_file() or not reject_path.is_file():
        raise PortError("Kconfig or reject file is missing")

    reject = reject_path.read_text(encoding="utf-8")
    validate_reject(reject)
    text = path.read_text(encoding="utf-8")

    # Earlier hunks must already have installed the actual selectable CPU
    # profiles. Refuse to paper over a broader failed application.
    for marker in (
        "config GENERIC_CPU",
        "config MZEN5",
        "config MDIAMONDRAPIDS",
        "config X86_64_VERSION",
    ):
        if marker not in text:
            raise PortError(f"CPU optimization prerequisite is missing: {marker}")

    usercopy_old = (
        "\tdepends on MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || "
        "M586MMX || X86_GENERIC || MK7 || MEFFICEON"
    )
    usercopy_new = (
        "\tdepends on MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || "
        "M586MMX || X86_GENERIC || MK8 || MK7 || MEFFICEON || MCORE2 || "
        "MNEHALEM || MWESTMERE || MSILVERMONT || MGOLDMONT || MGOLDMONTPLUS || "
        "MSANDYBRIDGE || MIVYBRIDGE || MHASWELL || MBROADWELL || MSKYLAKE || "
        "MSKYLAKEX || MCANNONLAKE || MICELAKE_CLIENT || MICELAKE_SERVER || "
        "MCASCADELAKE || MCOOPERLAKE || MTIGERLAKE || MSAPPHIRERAPIDS || "
        "MROCKETLAKE || MALDERLAKE || MRAPTORLAKE || MMETEORLAKE || "
        "MEMERALDRAPIDS || MDIAMONDRAPIDS"
    )
    text = replace_once(text, usercopy_old, usercopy_new, "X86_INTEL_USERCOPY")

    checksum_old = (
        "\tdepends on MWINCHIP3D || MWINCHIPC6 || MCYRIXIII || MK7 || MK6 || "
        "MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M686 || "
        "MVIAC3_2 || MVIAC7 || MEFFICEON || MGEODE_LX || MATOM"
    )
    checksum_new = (
        "\tdepends on MWINCHIP3D || MWINCHIPC6 || MCYRIXIII || MK7 || MK6 || "
        "MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M686 || MK8 || "
        "MVIAC3_2 || MVIAC7 || MEFFICEON || MGEODE_LX || MCORE2 || MATOM || "
        "MK8SSE3 || MK10 || MBARCELONA || MBOBCAT || MJAGUAR || MBULLDOZER || "
        "MPILEDRIVER || MSTEAMROLLER || MEXCAVATOR || MZEN || MZEN2 || MZEN3 || "
        "MZEN4 || MZEN5 || MNEHALEM || MWESTMERE || MSILVERMONT || MGOLDMONT || "
        "MGOLDMONTPLUS || MSANDYBRIDGE || MIVYBRIDGE || MHASWELL || MBROADWELL || "
        "MSKYLAKE || MSKYLAKEX || MCANNONLAKE || MICELAKE_CLIENT || MICELAKE_SERVER || "
        "MCASCADELAKE || MCOOPERLAKE || MTIGERLAKE || MSAPPHIRERAPIDS || "
        "MROCKETLAKE || MALDERLAKE || MRAPTORLAKE || MMETEORLAKE || "
        "MEMERALDRAPIDS || MDIAMONDRAPIDS"
    )
    text = replace_once(text, checksum_old, checksum_new, "X86_USE_PPRO_CHECKSUM")

    pae_old = (
        "\tdepends on MCRUSOE || MEFFICEON || MCYRIXIII || MPENTIUM4 || MPENTIUMM || "
        "MPENTIUMIII || MPENTIUMII || M686 || MVIAC7 || MATOM || X86_64"
    )
    pae_new = (
        "\tdepends on MCRUSOE || MEFFICEON || MCYRIXIII || MPENTIUM4 || MPENTIUMM || "
        "MPENTIUMIII || MPENTIUMII || M686 || MK8 || MVIAC7 || MCORE2 || MATOM || X86_64"
    )
    text = replace_once(text, pae_old, pae_new, "X86_HAVE_PAE")

    # Linux 7.2 intentionally has no CPU-model dependency on X86_TSC. The old
    # patch's dependency line is the stale context that caused this reject.
    tsc_block = "config X86_TSC\n\tdef_bool y\n\nconfig X86_HAVE_PAE\n"
    if tsc_block not in text:
        raise PortError("Linux 7.2 unconditional X86_TSC block was not preserved")

    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: port-cpu-optimizations-7.2.py <arch/x86/Kconfig.cpu> "
            "<arch/x86/Kconfig.cpu.rej> <kernel-version>"
        )
    try:
        port_kconfig(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    except PortError as exc:
        raise SystemExit(f"CPU optimization port failed: {exc}") from exc
    print("Applied deterministic Linux 7.2 CPU optimization Kconfig adapter")
