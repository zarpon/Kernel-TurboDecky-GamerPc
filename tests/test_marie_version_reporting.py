#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MarieVersionReportingTest(unittest.TestCase):
    def test_build_uses_current_upstream_without_local_fallback(self) -> None:
        core = (ROOT / "scripts/build-kernelnote-core.sh").read_text(encoding="utf-8")
        self.assertIn("Fetching current locked Marie LRU $PATCH_MARIE_VERSION testing source locally", core)
        self.assertIn("Marie source policy: current upstream testing release only", core)
        self.assertIn("Applying Marie LRU $PATCH_MARIE_VERSION upstream testing patch", core)
        self.assertNotIn("MARIE_FALLBACK_PATCH", core)
        self.assertNotIn("MARIE_FALLBACK_METADATA", core)
        self.assertNotIn("using maintained local fallback", core)
        self.assertNotIn("validate-marie-fallback.py", core)

    def test_dynamic_rewriter_sets_locked_marie_version(self) -> None:
        rewriter = (ROOT / "scripts/apply-dynamic-patch-sources.py").read_text(encoding="utf-8")
        self.assertIn('replace_assignment(text, "PATCH_MARIE_VERSION", versions["MARIE"])', rewriter)

    def test_audit_requires_upstream_only_marie(self) -> None:
        audit = (ROOT / "PATCH-AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("sem fallback local", audit)
        self.assertNotIn("fallback local é sincronizado automaticamente", audit)


if __name__ == "__main__":
    unittest.main()
