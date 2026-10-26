#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CASTVersionReportingTest(unittest.TestCase):
    def test_build_uses_current_upstream_without_local_fallback(self) -> None:
        core = (ROOT / "scripts/build-kernelnote-core.sh").read_text(encoding="utf-8")
        self.assertIn("Fetching current locked CAST LRU $PATCH_CAST_VERSION source locally", core)
        self.assertIn("CAST source policy: latest upstream release, native variant first within that release", core)
        self.assertIn("Applying CAST LRU $PATCH_CAST_VERSION (latest locked upstream release)", core)
        self.assertIn("port-lru-cast-latest.py", core)
        self.assertIn("02-lru-cast-compatibility-port.log", core)
        self.assertNotIn("CAST_FALLBACK_PATCH", core)
        self.assertNotIn("CAST_FALLBACK_METADATA", core)
        self.assertNotIn("using maintained local fallback", core)
        self.assertNotIn("validate-cast-fallback.py", core)

    def test_dynamic_rewriter_sets_locked_cast_version(self) -> None:
        rewriter = (ROOT / "scripts/apply-dynamic-patch-sources.py").read_text(encoding="utf-8")
        self.assertIn('replace_assignment(text, "PATCH_CAST_VERSION", versions["CAST"])', rewriter)

    def test_audit_requires_upstream_only_cast(self) -> None:
        audit = (ROOT / "PATCH-AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("sem fallback local", audit)
        self.assertNotIn("fallback local é sincronizado automaticamente", audit)


if __name__ == "__main__":
    unittest.main()
