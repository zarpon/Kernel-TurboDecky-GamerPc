#!/usr/bin/env python3
"""Set the dynamic generic Zarpon kernel identity and Polly toolchain mode."""

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
        r'''apply_requested_patch_series

# Ubuntu's Clang 18 already registers Polly in libLLVM. Loading LLVMPolly.so on
# top of that registers the same command-line options twice and aborts the
# compiler. Prefer the built-in implementation and rewrite the CachyOS Kconfig
# probe/Makefile flags accordingly. Keep the shared plugin as a fallback for a
# Clang build that does not contain Polly.
if printf 'int main(void) { return 0; }\n' | \
    clang -x c -c -o /dev/null - -mllvm -polly \
      > "$LOGDIR/polly-builtin-probe.log" 2>&1; then
  python3 - <<'PY'
from pathlib import Path

makefile = Path("Makefile")
lines = makefile.read_text(encoding="utf-8").splitlines(keepends=True)
changed = False
for index, line in enumerate(lines):
    if "KBUILD_CFLAGS" in line and "-fplugin=LLVMPolly.so" in line:
        lines[index] = line.replace("-fplugin=LLVMPolly.so", "-mllvm -polly")
        if index + 1 < len(lines) and "-mllvm -polly" in lines[index + 1]:
            del lines[index + 1]
        changed = True
        break
if not changed:
    raise SystemExit("Clang Polly Makefile plugin flag was not found")
makefile.write_text("".join(lines), encoding="utf-8")

kconfig = Path("init/Kconfig")
text = kconfig.read_text(encoding="utf-8")
old = "$(cc-option,-mllvm -polly -fplugin=LLVMPolly.so)"
new = "$(cc-option,-mllvm -polly)"
if text.count(old) != 1:
    raise SystemExit(f"Clang Polly Kconfig plugin probe count was {text.count(old)}, expected 1")
kconfig.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
  {
    echo "Polly mode: built into Clang"
    echo "Probe flags: -mllvm -polly"
    echo "LLVMPolly.so deliberately not loaded to avoid duplicate option registration"
  } | tee "$LOGDIR/polly-mode.txt"
  ! grep -Fq -- '-fplugin=LLVMPolly.so' Makefile
  ! grep -Fq -- '-fplugin=LLVMPolly.so' init/Kconfig
else
  test -n "${LLVM_POLLY_SO:-}"
  test -f "$LLVM_POLLY_SO"
  ln -sfn "$LLVM_POLLY_SO" "$KERNELDIR/LLVMPolly.so"
  export LD_LIBRARY_PATH="$KERNELDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  printf 'int main(void) { return 0; }\n' | \
    clang -x c -c -o /dev/null - -mllvm -polly -fplugin=LLVMPolly.so \
      > "$LOGDIR/polly-plugin-probe.log" 2>&1
  {
    echo "Polly mode: external LLVMPolly.so plugin"
    echo "Plugin: $LLVM_POLLY_SO"
    echo "Probe flags: -mllvm -polly -fplugin=LLVMPolly.so"
  } | tee "$LOGDIR/polly-mode.txt"
fi

git diff --check -- Makefile init/Kconfig | tee "$LOGDIR/polly-toolchain-diff-check.log"

# Fixed target: HP 240 G4 with Intel Core i3-5005U (Broadwell-U),
''',
        "Polly toolchain selection",
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
