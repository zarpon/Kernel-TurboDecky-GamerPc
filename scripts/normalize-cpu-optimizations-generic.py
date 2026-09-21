#!/usr/bin/env python3
"""Normalize the CPU-optimization patch for TurboDecky's generic amd64 target."""
from __future__ import annotations

import re
import sys
from pathlib import Path


class NormalizeError(RuntimeError):
    pass


NATIVE_GATE = "\tdepends on !X86_NATIVE_CPU\n"
CHOICE_WITH_NATIVE_GATE = (
    "choice\n"
    "\tprompt \"x86_64 Compiler Build Optimization\"\n"
    "\tdepends on !X86_NATIVE_CPU\n"
    "\tdefault GENERIC_CPU\n"
)
GENERIC_CHOICE = (
    "choice\n"
    "\tprompt \"x86_64 Compiler Build Optimization\"\n"
    "\tdefault GENERIC_CPU\n"
)


def normalize(kconfig_path: Path, makefile_path: Path) -> bool:
    if not kconfig_path.is_file() or not makefile_path.is_file():
        raise NormalizeError("Kconfig.cpu or arch/x86/Makefile is missing")

    text = kconfig_path.read_text(encoding="utf-8")
    gate_count = text.count(NATIVE_GATE)
    changed = False

    if gate_count > 1:
        raise NormalizeError(
            f"unexpected native-CPU choice gating count: {gate_count}"
        )
    if gate_count == 1:
        block_count = text.count(CHOICE_WITH_NATIVE_GATE)
        if block_count != 1:
            raise NormalizeError(
                "native-CPU gate exists outside the expected x86_64 optimization choice"
            )
        text = text.replace(CHOICE_WITH_NATIVE_GATE, GENERIC_CHOICE, 1)
        changed = True

    if NATIVE_GATE in text:
        raise NormalizeError("native-CPU choice gating remains after normalization")
    for marker in (
        'prompt "x86_64 Compiler Build Optimization"',
        "config GENERIC_CPU",
        "config X86_64_VERSION",
    ):
        if marker not in text:
            raise NormalizeError(f"CPU optimization marker is missing: {marker}")

    makefile = makefile_path.read_text(encoding="utf-8")
    if "-march=native" in makefile:
        guarded_native = re.search(
            r"ifdef CONFIG_X86_NATIVE_CPU\n"
            r"(?:[^\n]*\n){0,6}?"
            r"\s*KBUILD_CFLAGS\s*\+=\s*-march=native\s*$",
            makefile,
            re.MULTILINE,
        )
        if guarded_native is None:
            raise NormalizeError("unguarded -march=native detected in arch/x86/Makefile")

    if changed:
        kconfig_path.write_text(text, encoding="utf-8")
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: normalize-cpu-optimizations-generic.py "
            "<arch/x86/Kconfig.cpu> <arch/x86/Makefile>"
        )
    try:
        changed = normalize(Path(sys.argv[1]), Path(sys.argv[2]))
    except NormalizeError as exc:
        raise SystemExit(f"generic CPU optimization normalization failed: {exc}") from exc
    state = "removed native-CPU choice gate" if changed else "native-CPU choice gate already absent"
    print(f"Generic amd64 CPU optimization policy: {state}; -march=native remains forbidden")
