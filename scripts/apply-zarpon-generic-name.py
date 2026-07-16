#!/usr/bin/env python3
"""Set the dynamic generic Zarpon kernel identity and Polly plugin path."""

from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)


def patch_core(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        'MAKE=(make LLVM=1 LLVM_IAS=1)\n',
        ''': "${KERNEL_RELEASE_NAME:?latest stable kernel identity was not resolved}"
# The universal CPU-optimization patch selects -march=broadwell through
# CONFIG_MBROADWELL. Never use -march=native, which would target the GitHub
# runner. KERNELRELEASE controls uname -r, module paths, vermagic, installed
# image names and Debian package names.
MAKE=(make LLVM=1 LLVM_IAS=1 KERNELRELEASE="$KERNEL_RELEASE_NAME")
''',
        "dynamic Zarpon KERNELRELEASE",
    )

    source = replace_once(
        source,
        '''apply_requested_patch_series

# Fixed target: HP 240 G4 with Intel Core i3-5005U (Broadwell-U),
''',
        '''apply_requested_patch_series

# The CachyOS Polly patch loads LLVMPolly.so by name. Expose the exact plugin
# installed by the workflow in the kernel source directory before olddefconfig
# probes CONFIG_POLLY_CLANG and before compilation starts.
test -n "${LLVM_POLLY_SO:-}"
test -f "$LLVM_POLLY_SO"
ln -sfn "$LLVM_POLLY_SO" "$KERNELDIR/LLVMPolly.so"

# Fixed target: HP 240 G4 with Intel Core i3-5005U (Broadwell-U),
''',
        "Polly plugin exposure",
    )

    path.write_text(source, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    old_local = '-kn-marie-bore-poc-nap-rfx-adios-zir-lto'
    source = replace_once(source, old_local, "", "generic Zarpon localversion")

    emitted = '''kernel_release="$("${MAKE[@]}" -s kernelrelease)"
printf '%s\\n' "$kernel_release" | tee "$LOGDIR/kernelrelease.txt"
if ((${#kernel_release} > 64)); then
  echo "Kernel release exceeds the 64-character UTS_RELEASE limit: ${#kernel_release}" >&2
  exit 1
fi
'''
    replacement = emitted + '''if [[ "$kernel_release" != "$KERNEL_RELEASE_NAME" ]]; then
  echo "Unexpected kernel release: $kernel_release (expected $KERNEL_RELEASE_NAME)" >&2
  exit 1
fi
'''
    source = replace_once(source, emitted, replacement, "generic Zarpon release validation")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: apply-zarpon-generic-name.py <build-kernelnote-core.sh> "
            "<build-kernelnote.sh>"
        )
    patch_core(Path(sys.argv[1]))
    patch_wrapper(Path(sys.argv[2]))


if __name__ == "__main__":
    main()
