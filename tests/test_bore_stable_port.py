#!/usr/bin/env python3
"""Regression tests for the reviewed BORE stable-kernel port."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/apply-latest-stable-series.py"
SPEC = importlib.util.spec_from_file_location("latest_stable", MODULE_PATH)
assert SPEC and SPEC.loader
latest_stable = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(latest_stable)


class BoreStablePortTests(unittest.TestCase):
    def test_linux_715_replaces_only_obsolete_dequeue_hunk(self) -> None:
        base = latest_stable.BORE_BASE_PATCH.read_text(encoding="utf-8")
        adapted = latest_stable.adapt_bore_text(base, "7.1.5")

        self.assertIn(
            "Subject: [PATCH] sched: port BORE 6.8.0-rc1 to Linux 7.1.5",
            adapted,
        )
        self.assertNotIn(
            "util_est_update(&rq->cfs, p, flags & DEQUEUE_SLEEP);",
            adapted,
        )
        self.assertEqual(adapted.count("restart_burst_bore(p);"), 1)
        self.assertEqual(
            adapted.count("static bool dequeue_task_fair(struct rq *rq"), 1
        )

        hunk = adapted.split(
            "@@ -7427,6 +7523,19 @@ static bool dequeue_task_fair", 1
        )[1].split("@@ ", 1)[0]
        self.assertLess(
            hunk.index("restart_burst_bore(p);"),
            hunk.index("dequeue_entities(rq, &p->se, flags)"),
        )

    def test_linux_714_keeps_reviewed_patch_byte_identical(self) -> None:
        base = latest_stable.BORE_BASE_PATCH.read_text(encoding="utf-8")
        self.assertEqual(latest_stable.adapt_bore_text(base, "7.1.4"), base)

    def test_unknown_stable_version_fails_closed(self) -> None:
        base = latest_stable.BORE_BASE_PATCH.read_text(encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "no reviewed BORE"):
            latest_stable.adapt_bore_text(base, "7.1.6")


if __name__ == "__main__":
    unittest.main()
