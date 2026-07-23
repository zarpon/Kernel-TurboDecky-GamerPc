#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/apply-zen-interactive.py"

spec = importlib.util.spec_from_file_location("apply_zen_interactive", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class ZenInteractiveRewriterTests(unittest.TestCase):
    def test_rewriter_enables_and_asserts_zen_interactive(self) -> None:
        original = (
            "scripts/config --enable SCHED_BORE\n"
            "scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n"
            "assert_config \"CONFIG_SCHED_BORE=y\"\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text(original, encoding="utf-8")
            module.rewrite(path)
            result = path.read_text(encoding="utf-8")
            self.assertIn("scripts/config --enable ZEN_INTERACTIVE", result)
            self.assertIn('assert_config "CONFIG_ZEN_INTERACTIVE=y"', result)
            module.rewrite(path)
            self.assertEqual(result, path.read_text(encoding="utf-8"))

    def test_rewriter_rejects_missing_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text("echo no anchors\n", encoding="utf-8")
            with self.assertRaises(module.RewriteError):
                module.rewrite(path)


if __name__ == "__main__":
    unittest.main()
