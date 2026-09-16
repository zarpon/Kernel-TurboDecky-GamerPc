#!/usr/bin/env python3
"""Regression tests for deferring BORE to the dynamic lock finalizer."""

from __future__ import annotations

import importlib.util
import inspect
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/apply-latest-stable-series.py"
WORKFLOW = ROOT / ".github/workflows/validate-kernel.yml"
SPEC = importlib.util.spec_from_file_location("latest_stable", MODULE_PATH)
assert SPEC and SPEC.loader
latest_stable = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(latest_stable)


class BoreStablePortTests(unittest.TestCase):
    def test_latest_stable_rewriter_does_not_carry_a_version_specific_bore_port(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("materialize_bore_port", source)
        self.assertNotIn("BORE_SUPPORTED_KERNELS", source)
        self.assertNotIn("6.8.0-rc1", source)

    def test_latest_stable_rewrite_leaves_bore_for_the_locked_finalizer(self) -> None:
        implementation = inspect.getsource(latest_stable.patch_core)
        self.assertNotIn("BORE_", implementation)
        self.assertNotIn("bore", implementation.lower())

    def test_dynamic_finalizer_runs_after_the_series_rewrite(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        latest = "python3 scripts/apply-latest-stable-series.py scripts/build-kernelnote-core.sh"
        finalizer = "python3 scripts/finalize-bore-stable-port.py scripts/build-kernelnote-core.sh"
        self.assertIn(latest, workflow)
        self.assertIn(finalizer, workflow)
        self.assertLess(workflow.index(latest), workflow.index(finalizer))


if __name__ == "__main__":
    unittest.main()
