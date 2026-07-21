#!/usr/bin/env python3
"""Keep external-module builds compatible with the Clang TurboDecky kernel."""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "# TurboDecky: default external-module builds to the kernel LLVM toolchain."
LLVM_BLOCK_ANCHOR = "ifneq ($(LLVM),)\nifneq ($(filter %/,$(LLVM)),)\n"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old!r}")
    return text.replace(old, new, 1)


def patch_makefile(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return

    # Linux has more than one generic `ifneq ($(LLVM),)` stanza. Anchor the
    # change to the compiler-selection block, immediately before LLVM_PREFIX,
    # instead of matching the short expression globally.
    text = replace_once(
        text,
        LLVM_BLOCK_ANCHOR,
        f'''{MARKER}
ifeq ("$(origin LLVM)", "undefined")
ifneq ($(KBUILD_EXTMOD),)
LLVM := 1
endif
endif

{LLVM_BLOCK_ANCHOR}''',
        "LLVM external-module compiler-selection block",
    )

    # Polly optimizes the kernel itself. External modules must not require the
    # distro Clang package to provide the exact Polly implementation used by CI.
    text = replace_once(
        text,
        "ifdef CONFIG_POLLY_CLANG\nKBUILD_CFLAGS",
        "ifdef CONFIG_POLLY_CLANG\nifeq ($(KBUILD_EXTMOD),)\nKBUILD_CFLAGS",
        "Polly external-module guard start",
    )
    text = replace_once(
        text,
        "endif\n\n# Tell gcc to never replace conditional load with a non-conditional one\n",
        "endif\nendif\n\n# Tell gcc to never replace conditional load with a non-conditional one\n",
        "Polly external-module guard end",
    )

    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-external-module-toolchain.py <kernel-Makefile>")
    patch_makefile(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
