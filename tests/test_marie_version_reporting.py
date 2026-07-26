#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MarieVersionReportingTest(unittest.TestCase):
    def test_build_messages_and_fallback_use_current_metadata(self) -> None:
        core = (ROOT / "scripts/build-kernelnote-core.sh").read_text(encoding="utf-8")
        metadata = json.loads(
            (ROOT / "patches/fallback/lru_marie.json").read_text(encoding="utf-8")
        )
        version = metadata["project_version"]
        self.assertIn(
            f'PATCH_MARIE_VERSION="${{PATCH_MARIE_VERSION:-{version}}}"', core
        )
        self.assertIn(
            'MARIE_FALLBACK_PATCH="$ROOT/patches/fallback/lru_marie.patch"', core
        )
        self.assertIn(
            'Fetching pinned Marie LRU $PATCH_MARIE_VERSION testing source', core
        )
        self.assertIn("using maintained local fallback", core)
        self.assertIn(
            'Applying local Marie LRU $PATCH_MARIE_VERSION testing patch', core
        )
        self.assertIn(
            'Marie LRU $PATCH_MARIE_VERSION testing patch applied successfully', core
        )
        self.assertIsNone(re.search(r'Marie LRU 0\.7\.7', core))

    def test_dynamic_rewriter_replaces_fallback_default(self) -> None:
        rewriter = (ROOT / "scripts/apply-dynamic-patch-sources.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'replace_assignment(text, "PATCH_MARIE_VERSION", versions["MARIE"])',
            rewriter,
        )
        self.assertNotIn(
            'MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"',
            rewriter,
        )

    def test_audit_describes_automatic_fallback_refresh(self) -> None:
        audit = (ROOT / "PATCH-AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("fallback local é sincronizado automaticamente", audit)
        self.assertNotIn("atualmente 0.7.7", audit)


if __name__ == "__main__":
    unittest.main()
