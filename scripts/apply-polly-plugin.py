#!/usr/bin/env python3
"""Expose the packaged LLVMPolly plugin inside the generated kernel tree."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-polly-plugin.py <build-kernelnote-core.sh>")
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    old = '''apply_requested_patch_series

# Fixed target: HP 240 G4 with Intel Core i3-5005U (Broadwell-U),
'''
    new = '''apply_requested_patch_series

# The CachyOS Polly patch loads LLVMPolly.so by name. Expose the exact plugin
# installed by the workflow in the kernel source directory before olddefconfig
# probes CONFIG_POLLY_CLANG and before any compilation command runs.
test -n "${LLVM_POLLY_SO:-}"
test -f "$LLVM_POLLY_SO"
ln -sfn "$LLVM_POLLY_SO" "$KERNELDIR/LLVMPolly.so"

# Fixed target: HP 240 G4 with Intel Core i3-5005U (Broadwell-U),
'''
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Polly plugin anchor: expected once, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
