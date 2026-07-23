#!/usr/bin/env python3
"""Port the non-conflicting CONFIG_ZEN_INTERACTIVE behavior from Zen 7.1.4.

Source baseline: zen-kernel/zen-kernel tag v7.1.4-zen1.

TurboDecky intentionally retains its stronger project-specific choices:
- BORE owns base-slice policy;
- ADIOS remains the default I/O scheduler;
- REFLEX remains the default CPUFreq governor.

This port therefore applies the remaining official Zen interactivity defaults:
THP background defrag, compact-unevictable off, swap readahead off, lower CFS
migration/bandwidth tunables, smaller load-balance batches, and split-lock
mitigation off by default.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "TurboDecky: Zen interactive port from v7.1.4-zen1"

ZEN_KCONFIG = '''config ZEN_INTERACTIVE
\tbool "Tune kernel for interactivity"
\tdefault y
\thelp
\t  Tunes the kernel for responsiveness at the cost of throughput and
\t  power usage. TurboDecky retains BORE, ADIOS and REFLEX ownership of
\t  their respective policies while applying the non-conflicting Zen
\t  memory and scheduler latency defaults.
'''


class PortError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PortError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement, label: str) -> str:
    regex = re.compile(pattern, re.MULTILINE)
    matches = list(regex.finditer(text))
    if len(matches) != 1:
        raise PortError(f"{label}: expected one anchor, found {len(matches)}")
    return regex.sub(replacement, text, count=1)


def patch_init_kconfig(text: str) -> str:
    if MARKER in text:
        if "config ZEN_INTERACTIVE" not in text:
            raise PortError("init/Kconfig has a partial Zen interactive port")
        return text
    block = f'menu "General setup"\n\n# {MARKER}\n{ZEN_KCONFIG}\n'
    return replace_once(text, 'menu "General setup"\n\n', block, "init/Kconfig")


def patch_mm_kconfig(text: str) -> str:
    new = "\tdefault 0 if PREEMPT_RT || ZEN_INTERACTIVE\n\tdefault 1\n"
    if new in text:
        return text
    old = "\tdefault 0 if PREEMPT_RT\n\tdefault 1\n"
    return replace_once(text, old, new, "mm/Kconfig compact unevictable")


def patch_huge_memory(text: str) -> str:
    new = (
        "#ifdef CONFIG_ZEN_INTERACTIVE\n"
        "\t(1<<TRANSPARENT_HUGEPAGE_DEFRAG_KSWAPD_OR_MADV_FLAG)|\n"
        "#else\n"
        "\t(1<<TRANSPARENT_HUGEPAGE_DEFRAG_REQ_MADV_FLAG)|\n"
        "#endif\n"
    )
    if new in text:
        return text
    old = "\t(1<<TRANSPARENT_HUGEPAGE_DEFRAG_REQ_MADV_FLAG)|\n"
    return replace_once(text, old, new, "mm/huge_memory.c THP defrag")


def patch_swap(text: str) -> str:
    new = '''void __init swap_setup(void)
{
#ifdef CONFIG_ZEN_INTERACTIVE
\t/* Only swap-in pages requested, avoid readahead */
\tpage_cluster = 0;
#else
\tunsigned long megs = PAGES_TO_MB(totalram_pages());

\t/* Use a smaller cluster for small-memory machines */
\tif (megs < 16)
\t\tpage_cluster = 2;
\telse
\t\tpage_cluster = 3;
\t/*
\t * Right now other parts of the system means that we
\t * _really_ don't want to cluster much more
\t */
#endif

\tregister_sysctl_init("vm", swap_sysctl_table);
}
'''
    if new in text:
        return text
    old = '''void __init swap_setup(void)
{
\tunsigned long megs = PAGES_TO_MB(totalram_pages());

\t/* Use a smaller cluster for small-memory machines */
\tif (megs < 16)
\t\tpage_cluster = 2;
\telse
\t\tpage_cluster = 3;
\t/*
\t * Right now other parts of the system means that we
\t * _really_ don't want to cluster much more
\t */

\tregister_sysctl_init("vm", swap_sysctl_table);
}
'''
    return replace_once(text, old, new, "mm/swap.c page cluster")


def _conditional_declaration(match: re.Match[str], zen_value: str, normal_value: str) -> str:
    declaration = match.group("decl")
    return (
        "#ifdef CONFIG_ZEN_INTERACTIVE\n"
        f"{declaration}{zen_value};\n"
        "#else\n"
        f"{declaration}{normal_value};\n"
        "#endif"
    )


def patch_fair(text: str) -> str:
    if "CONFIG_ZEN_INTERACTIVE\n" in text and "sysctl_sched_migration_cost" in text:
        migration_guarded = re.search(
            r"#ifdef CONFIG_ZEN_INTERACTIVE\n[^#]*sysctl_sched_migration_cost",
            text,
            re.DOTALL,
        )
    else:
        migration_guarded = None
    if not migration_guarded:
        text = replace_regex_once(
            text,
            r"^(?P<decl>\s*(?:(?:__read_mostly|const_debug)\s+)?unsigned int\s+"
            r"sysctl_sched_migration_cost\s*=\s*)500000UL;$",
            lambda match: _conditional_declaration(match, "300000UL", "500000UL"),
            "kernel/sched/fair.c migration cost",
        )

    bandwidth_block = (
        "#ifdef CONFIG_ZEN_INTERACTIVE\n"
        "static unsigned int sysctl_sched_cfs_bandwidth_slice\t\t= 3000UL;\n"
        "#else\n"
        "static unsigned int sysctl_sched_cfs_bandwidth_slice\t\t= 5000UL;\n"
        "#endif"
    )
    if bandwidth_block not in text:
        text = replace_regex_once(
            text,
            r"^\s*static unsigned int\s+sysctl_sched_cfs_bandwidth_slice\s*=\s*5000UL;$",
            bandwidth_block,
            "kernel/sched/fair.c bandwidth slice",
        )
    return text


def patch_sched_header(text: str) -> str:
    new = (
        "#if defined(CONFIG_PREEMPT_RT) || defined(CONFIG_ZEN_INTERACTIVE)\n"
        "# define SCHED_NR_MIGRATE_BREAK 8\n"
        "#else\n"
        "# define SCHED_NR_MIGRATE_BREAK 32\n"
        "#endif\n"
    )
    if new in text:
        return text
    old = (
        "#ifdef CONFIG_PREEMPT_RT\n"
        "# define SCHED_NR_MIGRATE_BREAK 8\n"
        "#else\n"
        "# define SCHED_NR_MIGRATE_BREAK 32\n"
        "#endif\n"
    )
    return replace_once(text, old, new, "kernel/sched/sched.h migration break")


def patch_ondemand(text: str) -> str:
    new = (
        "#if defined(CONFIG_ZEN_INTERACTIVE)\n"
        "#define DEF_FREQUENCY_UP_THRESHOLD\t\t(55)\n"
        "#define MICRO_FREQUENCY_UP_THRESHOLD\t\t(60)\n"
        "#define DEF_SAMPLING_DOWN_FACTOR\t\t(5)\n"
        "#else\n"
        "#define DEF_FREQUENCY_UP_THRESHOLD\t\t(80)\n"
        "#define MICRO_FREQUENCY_UP_THRESHOLD\t\t(95)\n"
        "#define DEF_SAMPLING_DOWN_FACTOR\t\t(1)\n"
        "#endif\n"
    )
    if new in text:
        return text
    old = (
        "#define DEF_FREQUENCY_UP_THRESHOLD\t\t(80)\n"
        "#define MICRO_FREQUENCY_UP_THRESHOLD\t\t(95)\n"
        "#define DEF_SAMPLING_DOWN_FACTOR\t\t(1)\n"
    )
    return replace_once(text, old, new, "cpufreq ondemand defaults")


def patch_bus_lock(text: str) -> str:
    new = (
        "#ifdef CONFIG_ZEN_INTERACTIVE\n"
        "static unsigned int sysctl_sld_mitigate;\n"
        "#else\n"
        "static unsigned int sysctl_sld_mitigate = 1;\n"
        "#endif\n"
    )
    if new in text:
        return text
    old = "static unsigned int sysctl_sld_mitigate = 1;\n"
    return replace_once(text, old, new, "x86 split-lock mitigation")


PATCHERS = {
    "init/Kconfig": patch_init_kconfig,
    "mm/Kconfig": patch_mm_kconfig,
    "mm/huge_memory.c": patch_huge_memory,
    "mm/swap.c": patch_swap,
    "kernel/sched/fair.c": patch_fair,
    "kernel/sched/sched.h": patch_sched_header,
    "drivers/cpufreq/cpufreq_ondemand.c": patch_ondemand,
    "arch/x86/kernel/cpu/bus_lock.c": patch_bus_lock,
}


def apply(root: Path) -> None:
    staged: dict[Path, str] = {}
    for relative, patcher in PATCHERS.items():
        path = root / relative
        if not path.is_file():
            raise PortError(f"required source file is missing: {relative}")
        original = path.read_text(encoding="utf-8")
        staged[path] = patcher(original)

    for path, content in staged.items():
        path.write_text(content, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-zen-interactive-source.py <kernel-source-dir>")
    root = Path(sys.argv[1]).resolve()
    try:
        apply(root)
    except (OSError, UnicodeDecodeError, PortError) as exc:
        raise SystemExit(f"Zen interactive source port failed: {exc}") from exc
    print(
        "Applied non-conflicting Zen interactive defaults from "
        "zen-kernel v7.1.4-zen1"
    )


if __name__ == "__main__":
    main()
