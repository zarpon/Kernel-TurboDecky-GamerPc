#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/apply-zen-interactive-source.py"

spec = importlib.util.spec_from_file_location("apply_zen_interactive_source", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


FIXTURES = {
    "init/Kconfig": 'menu "General setup"\n\nconfig BROKEN\n\tbool\n',
    "mm/Kconfig": (
        "config COMPACT_UNEVICTABLE_DEFAULT\n"
        "\tint\n"
        "\tdepends on COMPACTION\n"
        "\tdefault 0 if PREEMPT_RT\n"
        "\tdefault 1\n"
    ),
    "mm/huge_memory.c": (
        "unsigned long transparent_hugepage_flags =\n"
        "\t(1<<TRANSPARENT_HUGEPAGE_DEFRAG_REQ_MADV_FLAG)|\n"
        "\t(1<<TRANSPARENT_HUGEPAGE_USE_ZERO_PAGE_FLAG);\n"
    ),
    "mm/swap.c": '''void __init swap_setup(void)
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
''',
    "kernel/sched/fair.c": (
        "const_debug unsigned int sysctl_sched_migration_cost = 500000UL;\n"
        "#ifdef CONFIG_CFS_BANDWIDTH\n"
        "static unsigned int sysctl_sched_cfs_bandwidth_slice = 5000UL;\n"
        "#endif\n"
    ),
    "kernel/sched/sched.h": (
        "#ifdef CONFIG_PREEMPT_RT\n"
        "# define SCHED_NR_MIGRATE_BREAK 8\n"
        "#else\n"
        "# define SCHED_NR_MIGRATE_BREAK 32\n"
        "#endif\n"
    ),
    "drivers/cpufreq/cpufreq_ondemand.c": (
        "#define DEF_FREQUENCY_UP_THRESHOLD\t\t(80)\n"
        "#define MICRO_FREQUENCY_UP_THRESHOLD\t\t(95)\n"
        "#define DEF_SAMPLING_DOWN_FACTOR\t\t(1)\n"
    ),
    "arch/x86/kernel/cpu/bus_lock.c": (
        "static unsigned int sysctl_sld_mitigate = 1;\n"
    ),
}


class ZenInteractiveSourceTests(unittest.TestCase):
    def create_tree(self, root: Path) -> None:
        for relative, content in FIXTURES.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def test_port_is_complete_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_tree(root)
            module.apply(root)
            first = {
                relative: (root / relative).read_text(encoding="utf-8")
                for relative in FIXTURES
            }
            module.apply(root)
            second = {
                relative: (root / relative).read_text(encoding="utf-8")
                for relative in FIXTURES
            }

        self.assertEqual(first, second)
        self.assertIn("config ZEN_INTERACTIVE", first["init/Kconfig"])
        self.assertIn("PREEMPT_RT || ZEN_INTERACTIVE", first["mm/Kconfig"])
        self.assertIn("DEFRAG_KSWAPD_OR_MADV", first["mm/huge_memory.c"])
        self.assertIn("page_cluster = 0", first["mm/swap.c"])
        self.assertIn("300000UL", first["kernel/sched/fair.c"])
        self.assertIn("3000UL", first["kernel/sched/fair.c"])
        self.assertIn("CONFIG_ZEN_INTERACTIVE", first["kernel/sched/sched.h"])
        self.assertIn("DEF_FREQUENCY_UP_THRESHOLD\t\t(55)", first["drivers/cpufreq/cpufreq_ondemand.c"])
        self.assertIn("static unsigned int sysctl_sld_mitigate;", first["arch/x86/kernel/cpu/bus_lock.c"])

    def test_layout_change_fails_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_tree(root)
            broken = root / "mm/Kconfig"
            broken.write_text("config COMPACTION\n", encoding="utf-8")
            original_init = (root / "init/Kconfig").read_text(encoding="utf-8")
            with self.assertRaises(module.PortError):
                module.apply(root)
            after_init = (root / "init/Kconfig").read_text(encoding="utf-8")

        self.assertEqual(original_init, after_init)

    def test_project_specific_owners_are_not_replaced(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("BORE owns base-slice policy", source)
        self.assertIn("ADIOS remains the default I/O scheduler", source)
        self.assertIn("REFLEX remains the default CPUFreq governor", source)
        self.assertNotIn("ctx.name = \"kyber\"", source)
        self.assertNotIn(".name = \"bfq\"", source)


if __name__ == "__main__":
    unittest.main()
