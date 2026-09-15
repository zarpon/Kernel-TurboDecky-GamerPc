#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReflexBootstrapTests(unittest.TestCase):
    def test_bootstrap_is_lock_only_and_runtime_checks_are_dynamic(self) -> None:
        source = (ROOT / "scripts/apply-reflex-core.py").read_text(encoding="utf-8")
        self.assertIn('REFLEX_REPO="__DYNAMIC_PATCH_LOCK_REQUIRED__"', source)
        self.assertIn('REFLEX_COMMIT="__DYNAMIC_PATCH_LOCK_REQUIRED__"', source)
        self.assertIn('REFLEX_PATCH_PATH="__DYNAMIC_PATCH_LOCK_REQUIRED__"', source)
        self.assertIn('PATCH_REFLEX_VERSION="__DYNAMIC_PATCH_LOCK_REQUIRED__"', source)
        self.assertIn('REFLEX_PATCH="$PATCHDIR/0007-reflex-current.patch"', source)
        self.assertIn('grep -Fq "$PATCH_REFLEX_VERSION" drivers/cpufreq/cpufreq_reflex.c', source)
        self.assertIn("drivers/base/arch_topology.c", source)
        self.assertNotIn("a7205405c20a499fc1490e073fab03dc9a28e818", source)
        self.assertNotIn("linux7.1-reflex-v0.3.2", source)
        self.assertNotIn('CPUFREQ_REFLEX_VERSION  "0.3.1"', source)


if __name__ == "__main__":
    unittest.main()
