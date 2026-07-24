#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "scripts/port-zen-interactive.py"
FAST_RESOLVER = ROOT / "scripts/resolve-zen-interactive-fast.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


port = load("port_zen_interactive", PORT)


class ZenProjectPortTests(unittest.TestCase):
    def test_conflicting_adios_and_bore_hunks_are_replaced(self) -> None:
        patch = """diff --git a/block/elevator.c b/block/elevator.c
--- a/block/elevator.c
+++ b/block/elevator.c
@@ -1 +1,3 @@
+#ifdef CONFIG_ZEN_INTERACTIVE
 value
+#endif
diff --git a/kernel/sched/fair.c b/kernel/sched/fair.c
--- a/kernel/sched/fair.c
+++ b/kernel/sched/fair.c
@@ -1,3 +1,10 @@
 unsigned int sysctl_sched_base_slice = 700000ULL;
+#ifdef CONFIG_ZEN_INTERACTIVE
+__read_mostly unsigned int sysctl_sched_migration_cost = 300000UL;
+#else
 __read_mostly unsigned int sysctl_sched_migration_cost = 500000UL;
+#endif
 
@@ -15,3 +22,7 @@
 #ifdef CONFIG_CFS_BANDWIDTH
+#ifdef CONFIG_ZEN_INTERACTIVE
+static unsigned int sysctl_sched_cfs_bandwidth_slice = 3000UL;
+#else
 static unsigned int sysctl_sched_cfs_bandwidth_slice = 5000UL;
+#endif
 #endif
diff --git a/init/Kconfig b/init/Kconfig
--- a/init/Kconfig
+++ b/init/Kconfig
@@ -1 +1,7 @@
+config ZEN_INTERACTIVE
+\tbool "Tune"
+\thelp
+\t    Default scheduler for SQ..: bfq
+\t    Default scheduler for MQ..: kyber
+\t    Minimal granularity............: 0.4 ms
 menu "General"
"""
        adapted, exclusions = port.prepare_patch(patch)

        self.assertNotIn("block/elevator.c", port.patch_files(adapted))
        self.assertNotIn("sysctl_sched_base_slice", adapted)
        self.assertIn("sysctl_sched_migration_cost", adapted)
        self.assertIn("300000UL", adapted)
        self.assertIn("sysctl_sched_cfs_bandwidth_slice", adapted)
        self.assertIn("project policy unchanged", adapted)
        self.assertTrue(any("ADIOS" in item for item in exclusions))
        self.assertTrue(any("BORE" in item for item in exclusions))

    def test_migration_port_is_single_and_metadata_is_stable(self) -> None:
        patch = """diff --git a/kernel/sched/fair.c b/kernel/sched/fair.c
--- a/kernel/sched/fair.c
+++ b/kernel/sched/fair.c
@@ -1,3 +1,10 @@
 unsigned int sysctl_sched_base_slice = 700000ULL;
+#ifdef CONFIG_ZEN_INTERACTIVE
+__read_mostly unsigned int sysctl_sched_migration_cost = 300000UL;
+#else
 __read_mostly unsigned int sysctl_sched_migration_cost = 500000UL;
+#endif
 
diff --git a/init/Kconfig b/init/Kconfig
--- a/init/Kconfig
+++ b/init/Kconfig
@@ -1 +1,2 @@
+config ZEN_INTERACTIVE
 value
"""
        adapted, _ = port.prepare_patch(patch)

        self.assertEqual(adapted.count("sysctl_sched_migration_cost"), 3)
        self.assertEqual(port.patch_hunk_count(adapted), 2)
        self.assertEqual(
            port.patch_files(adapted),
            ["init/Kconfig", "kernel/sched/fair.c"],
        )

    def test_fast_resolver_updates_adapted_lock_and_provenance(self) -> None:
        source = FAST_RESOLVER.read_text(encoding="utf-8")
        self.assertIn("apply_project_policy()", source)
        self.assertIn('"io_scheduler_policy": "ADIOS-preserved"', source)
        self.assertIn('"base_slice_policy": "BORE-preserved"', source)
        self.assertIn('"migration_cost_ns": 300000', source)
        self.assertLess(source.index("resolver.main()"), source.index("apply_project_policy()", source.index("resolver.main()")))


if __name__ == "__main__":
    unittest.main()
