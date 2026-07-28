#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReflexBootstrapTests(unittest.TestCase):
    def test_bootstrap_is_current_and_runtime_checks_are_dynamic(self) -> None:
        source = (ROOT / "scripts/apply-reflex-core.py").read_text(encoding="utf-8")
        self.assertIn("a7205405c20a499fc1490e073fab03dc9a28e818", source)
        self.assertIn("patches/0001-linux7.1-reflex-v0.3.2.patch", source)
        self.assertIn('PATCH_REFLEX_VERSION="${PATCH_REFLEX_VERSION:-0.3.2}"', source)
        self.assertIn('grep -Fq "$PATCH_REFLEX_VERSION" drivers/cpufreq/cpufreq_reflex.c', source)
        self.assertIn("drivers/base/arch_topology.c", source)
        self.assertNotIn('CPUFREQ_REFLEX_VERSION  "0.3.1"', source)


if __name__ == "__main__":
    unittest.main()
