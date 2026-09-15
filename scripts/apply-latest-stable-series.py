#!/usr/bin/env python3
"""Follow the resolved stable series for non-scheduler build rewrites.

BORE is finalized from the build's dynamic patch lock after every source
resolver run. Keeping a second, version-specific BORE port here used to make
the preliminary rewrite fail as soon as Linux advanced beyond the small list
of hand-maintained versions, before the dynamic finalizer had a chance to run.
"""

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
        '[[ "$PATCH_MARIE_VERSION" == "unknown" ]] || grep -Fq "$PATCH_MARIE_VERSION" mm/lru_marie/version.h':
            '[[ "$PATCH_MARIE_VERSION" == "unknown" ]] || { marie_source_version="${PATCH_MARIE_VERSION%%r[0-9]*}"; grep -Fq "$marie_source_version" mm/lru_marie/version.h; }',
    }

    for old, new in replacements.items():
        if old in source:
            source = source.replace(old, new)
        elif new in source:
            continue
        else:
            raise SystemExit(f"latest-stable patch-series anchor missing: {old!r}")

    gud_fix = r'''fix_gud_full_lto_bounds() {
  local gud_source="drivers/gpu/drm/gud/gud_connector.c"

  # Linux 7.2.5 adds fixed-slot TV-mode validation. Under Clang Full LTO with
  # FORTIFY, make the USB transfer upper bound explicit before deriving slot
  # pointers; otherwise gud.o can terminate the link through __read_overflow.
  # This keeps GUD, FORTIFY and Full LTO enabled and only strengthens protocol
  # validation for an impossible/invalid oversized response.
  python3 - "$gud_source" <<'PYGUD'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = "if (!ret || ret % GUD_CONNECTOR_TV_MODE_NAME_LEN) {"
new = "if (!ret || ret > buf_len || ret % GUD_CONNECTOR_TV_MODE_NAME_LEN) {"
if new in text:
    changed = False
elif old in text:
    text = text.replace(old, new, 1)
    changed = True
else:
    raise SystemExit("GUD TV-mode bounds anchor changed; refusing unreviewed rewrite")
if text.count(new) != 1:
    raise SystemExit("unexpected GUD TV-mode bounds validation count")
path.write_text(text, encoding="utf-8")
print(f"GUD Full-LTO bounds fix changed={changed}")
PYGUD

  grep -Fq 'ret > buf_len' "$gud_source"
  git diff --check -- "$gud_source"
  echo "GUD TV-mode response: explicit ret <= buf_len invariant" \
    | tee -a "$LOGDIR/known-warning-fixes.txt"
}

'''
    if "fix_gud_full_lto_bounds() {" not in source:
        source = replace_once(source, "normalize_changed_whitespace() {\n", gud_fix + "normalize_changed_whitespace() {\n", "GUD Full-LTO source-fix function")
    if "\nfix_gud_full_lto_bounds\n\n" not in source:
        source = replace_once(source, "# choices instead of pruning the build for one computer model.\n", "# choices instead of pruning the build for one computer model.\nfix_gud_full_lto_bounds\n\n", "GUD Full-LTO source-fix call")

    path.write_text(source, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    pairs = [
        ('  "cpuidle.governor=nap"\n)\n', '  "cpuidle.governor=nap"\n  "kvm.enable_virt_at_load=0"\n)\n', "VirtualBox/KVM command line"),
        ('scripts/config --enable CPU_IDLE_GOV_NAP\n', 'scripts/config --enable CPU_IDLE_GOV_NAP\n# VirtualBox host drivers are external modules. Preserve the module loader,\n# symbol metadata and host-network devices they require.\nscripts/config --enable MODULES\nscripts/config --enable MODULE_UNLOAD\nscripts/config --enable MODULE_FORCE_UNLOAD\nscripts/config --enable KALLSYMS\nscripts/config --enable KALLSYMS_ALL\nscripts/config --enable VIRTUALIZATION\nscripts/config --module KVM\nscripts/config --module KVM_INTEL\nscripts/config --module KVM_AMD\nscripts/config --module TUN\nscripts/config --module BRIDGE\nscripts/config --enable NETFILTER\n', "VirtualBox host Kconfig"),
        ('assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"\n', 'assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"\nassert_config "CONFIG_MODULES=y"\nassert_config "CONFIG_MODULE_UNLOAD=y"\nassert_config "CONFIG_MODULE_FORCE_UNLOAD=y"\nassert_config "CONFIG_KALLSYMS=y"\nassert_config "CONFIG_KALLSYMS_ALL=y"\nassert_config "CONFIG_VIRTUALIZATION=y"\nassert_config "CONFIG_KVM=m"\nassert_config "CONFIG_KVM_INTEL=m"\nassert_config "CONFIG_KVM_AMD=m"\nassert_config "CONFIG_TUN=m"\nassert_config "CONFIG_BRIDGE=m"\nassert_config "CONFIG_NETFILTER=y"\n', "VirtualBox host Kconfig assertions"),
        ('assert_cmdline_token "cpuidle.governor=nap"\n', 'assert_cmdline_token "cpuidle.governor=nap"\nassert_cmdline_token "kvm.enable_virt_at_load=0"\n', "VirtualBox/KVM command-line assertion"),
    ]
    for old, new, label in pairs:
        if new in source:
            continue
        source = replace_once(source, old, new, label)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-latest-stable-series.py <generated-core-script>")
    core = Path(sys.argv[1])
    patch_core(core)
    patch_wrapper(core.with_name("build-kernelnote.sh"))


if __name__ == "__main__":
    main()
