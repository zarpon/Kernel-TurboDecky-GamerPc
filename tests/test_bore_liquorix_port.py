#!/usr/bin/env python3
"""Contract checks for the reviewed BORE port used by the Liquorix build."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "patches/bore/7.1.3-lqx1-bore-6.6.3.patch"
CORE = ROOT / "scripts/build-kernelnote-core.sh"
MANIFEST = ROOT / "config/patch-sources.json"


class BoreLiquorixPortTests(unittest.TestCase):
    def test_port_is_pinned_and_contains_the_scheduler_integration(self) -> None:
        data = PORT.read_bytes()
        self.assertEqual(
            hashlib.sha256(data).hexdigest(),
            "981d631e2ec97f42b638d3717c81d3b32de2f5baeca52c5f2037d3beea9a805e",
        )
        text = data.decode("utf-8")
        for marker in (
            "Subject: [PATCH] sched: adapt BORE 6.6.3 for Liquorix 7.1.3",
            "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c",
            "SCHED_BORE_VERSION  \"6.6.3\"",
            "obj-$(CONFIG_SCHED_BORE) += bore.o",
            "sched_update_min_base_slice",
        ):
            self.assertIn(marker, text)

    def test_build_tracks_upstream_but_applies_the_exact_local_port(self) -> None:
        core = CORE.read_text(encoding="utf-8")
        self.assertIn('BORE_REPO="https://github.com/firelzrd/bore-scheduler.git"', core)
        self.assertIn('BORE_PATCH_PATH="patches/stable/linux-7.1-bore/', core)
        self.assertIn('BORE_PATCH="$ROOT/patches/bore/7.1.3-lqx1-bore-6.6.3.patch"', core)
        self.assertIn('apply_bore_patch "$BORE_PATCH"', core)
        function = core.split("apply_bore_patch() {", 1)[1].split("apply_adios_patch() {", 1)[0]
        self.assertIn("--dry-run", function)
        self.assertNotIn("--fuzz", function)

    def test_dynamic_manifest_requires_native_bore_71_source(self) -> None:
        component = json.loads(MANIFEST.read_text(encoding="utf-8"))["components"]["bore"]
        self.assertEqual(component["repo"], "https://github.com/firelzrd/bore-scheduler.git")
        self.assertEqual(component["ref"], "main")
        self.assertTrue(component["require_exact_series"])
        self.assertEqual(component["output"], "01-bore.patch")
        self.assertIn("linux-{series}-bore", component["exact_globs"][0])


if __name__ == "__main__":
    unittest.main()
