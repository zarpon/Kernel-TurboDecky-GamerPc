#!/usr/bin/env python3
"""Set the dynamic TurboDecky identity, Polly mode, VRAM and patch resolution."""

from __future__ import annotations

import os
import subprocess
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
# Keep the generic x86-64 CPU Kconfig choice and never use -march=native,
# which would target the GitHub runner. KERNELRELEASE controls uname -r,
# module paths, vermagic, installed image names and Debian package names.
MAKE=(make LLVM=1 LLVM_IAS=1 KERNELRELEASE="$KERNEL_RELEASE_NAME")
''',
        "dynamic TurboDecky KERNELRELEASE",
    )

    source = replace_once(
        source,
        '  "${MAKE[@]}" -j"$JOBS" bindeb-pkg ',
        '  "${MAKE[@]}" -j"$JOBS" '
        'DEPMOD="$ROOT/scripts/depmod-turbodecky.sh" bindeb-pkg ',
        "depmod compatibility for linux.* release names",
    )

    source = replace_once(
        source,
        '''apply_requested_patch_series

# Generic amd64 profile: keep the upstream platform, topology and driver
# choices instead of pruning the build for one computer model.
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

# The packaged headers retain Clang-only flags. Make external modules use LLVM
# automatically and keep kernel-only Polly flags out of DKMS/VirtualBox.
python3 "$ROOT/scripts/patch-external-module-toolchain.py" Makefile
grep -Fq 'TurboDecky: default external-module builds' Makefile
grep -Fq 'ifeq ($(KBUILD_EXTMOD),)' Makefile

# Generic x86-64 target with the upstream platform and driver matrix,
''',
        "Polly toolchain selection",
    )

    # Retain vendored OpenWrt copies only as emergency fallbacks. The dynamic
    # resolver inserted later always places its branch-head snapshot first.
    openwrt_commit = "0ff1553bd731c0db28043fc9caab90bdc32587f3"
    openwrt_paths = (
        "package/kernel/mac80211/patches/subsys/302-mac80211-minstrel_ht-fix-MINSTREL_FRAC-macro.patch",
        "package/kernel/mac80211/patches/subsys/303-mac80211-minstrel_ht-reduce-fluctuations-in-rate-pro.patch",
        "package/kernel/mac80211/patches/subsys/304-mac80211-minstrel_ht-rework-rate-downgrade-code-and-.patch",
        "package/kernel/mac80211/patches/ath11k/910-ath11k-fix-remapped-ce-accessing-issue-on-64bit-OS.patch",
    )
    vendored_names = {
        "package/kernel/mac80211/patches/subsys/304-mac80211-minstrel_ht-rework-rate-downgrade-code-and-.patch":
            "304-mac80211-minstrel_ht-rework-rate-downgrade-code-and--linux7.1-port.patch",
    }
    for patch_path in openwrt_paths:
        vendored = (
            "file://$ROOT/patches/openwrt-0ff1553/"
            f"{vendored_names.get(patch_path, Path(patch_path).name)}"
        )
        primary = (
            "https://git.openwrt.org/openwrt/openwrt/plain/"
            f"{patch_path}?id={openwrt_commit}"
        )
        mirror = (
            "https://raw.githubusercontent.com/openwrt/openwrt/"
            f"{openwrt_commit}/{patch_path}"
        )
        source = replace_once(
            source,
            f'"{primary}"',
            f'"{vendored}" \\' + "\n    " +
            f'"{primary}" \\' + "\n    " + f'"{mirror}"',
            f"OpenWrt mirror for {Path(patch_path).name}",
        )

    path.write_text(source, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    old_local = '-kn-marie-bore-poc-nap-rfx-adios-zir-lto'
    source = replace_once(source, old_local, "", "generic TurboDecky localversion")

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
    source = replace_once(source, emitted, replacement, "generic TurboDecky release validation")
    path.write_text(source, encoding="utf-8")


def run_logged(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout or ""
    log_path.write_text(output, encoding="utf-8")
    print(output, end="")
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, command)


def resolve_and_lock_sources(core: Path, wrapper: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    kernel_version = os.environ.get("KERNEL_VERSION")
    kernel_series = os.environ.get("KERNEL_SERIES")
    if not kernel_version or not kernel_series:
        raise SystemExit("KERNEL_VERSION and KERNEL_SERIES must be resolved before patch selection")

    manifest = root / "config/patch-sources.json"
    resolver = root / "scripts/resolve-patch-sources.py"
    rewriter = root / "scripts/apply-dynamic-patch-sources.py"
    warning_rewriter = root / "scripts/apply-known-warning-fixes.py"
    validation_rewriter = root / "scripts/apply-validation-modules.py"
    output = root / ".resolved-patches"
    logs = root / "logs"
    run_logged(
        [
            sys.executable,
            str(resolver),
            "--manifest", str(manifest),
            "--output-dir", str(output),
            "--kernel-version", kernel_version,
            "--kernel-series", kernel_series,
            "--summary", str(output / "resolution-summary.txt"),
        ],
        logs / "patch-source-resolution.log",
    )
    lock = output / "patch-lock.json"
    run_logged(
        [sys.executable, str(rewriter), str(core), str(wrapper), str(lock)],
        logs / "patch-source-rewrite.log",
    )
    run_logged(
        [sys.executable, str(warning_rewriter), str(core)],
        logs / "known-warning-fixes-rewrite.log",
    )
    run_logged(
        [sys.executable, str(validation_rewriter), str(core)],
        logs / "validation-modules-rewrite.log",
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: apply-zarpon-generic-name.py <build-kernelnote-core.sh> "
            "<build-kernelnote.sh>"
        )
    core = Path(sys.argv[1])
    wrapper = Path(sys.argv[2])
    patch_core(core)
    patch_wrapper(wrapper)
    vram_integrator = Path(__file__).with_name("apply-vram-cgroup.py")
    subprocess.run([sys.executable, str(vram_integrator), str(wrapper)], check=True)
    resolve_and_lock_sources(core, wrapper)


if __name__ == "__main__":
    main()
