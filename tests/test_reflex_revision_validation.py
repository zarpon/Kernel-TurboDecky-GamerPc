#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REWRITER = (ROOT / "scripts/apply-reflex-core.py").read_text(encoding="utf-8")


class ReflexRevisionValidationTest(unittest.TestCase):
    def test_patch_revision_is_not_required_in_runtime_version_macro(self) -> None:
        self.assertIn("sed -E 's/r[0-9]+$//'", REWRITER)
        self.assertIn(
            'grep -Fq "#define CPUFREQ_REFLEX_VERSION  \\"$runtime_version\\""',
            REWRITER,
        )
        self.assertNotIn(
            'grep -Fq "$PATCH_REFLEX_VERSION" drivers/cpufreq/cpufreq_reflex.c',
            REWRITER,
        )


if __name__ == "__main__":
    unittest.main()
