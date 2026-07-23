#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/apply-zen-interactive-config.py"
CONFIG = ROOT / "config/kernelnote.config"

spec = importlib.util.spec_from_file_location("apply_zen_interactive_config", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class ZenInteractiveConfigTests(unittest.TestCase):
    def test_static_override_enables_symbol(self) -> None:
        text = CONFIG.read_text(encoding="utf-8")
        self.assertEqual(text.count("CONFIG_ZEN_INTERACTIVE=y"), 1)

    def test_generated_build_ports_enables_and_asserts_symbol(self) -> None:
        source = (
            "apply_requested_patch_series\n"
            "scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n"
            "assert_config \"CONFIG_SCHED_BORE=y\"\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "build-kernelnote-core.sh"
            target.write_text(source, encoding="utf-8")

            original_argv = module.sys.argv
            try:
                module.sys.argv = [str(SCRIPT), str(target)]
                module.main()
                first = target.read_text(encoding="utf-8")
                module.main()
                second = target.read_text(encoding="utf-8")
            finally:
                module.sys.argv = original_argv

        self.assertEqual(first, second)
        self.assertEqual(first.count("apply-zen-interactive-source.py"), 1)
        self.assertEqual(first.count("scripts/config --enable ZEN_INTERACTIVE"), 1)
        self.assertEqual(first.count('assert_config "CONFIG_ZEN_INTERACTIVE=y"'), 1)

    def test_partial_integration_is_rejected(self) -> None:
        source = (
            "apply_requested_patch_series\n"
            "scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n"
            "scripts/config --enable ZEN_INTERACTIVE\n"
            "assert_config \"CONFIG_SCHED_BORE=y\"\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "build-kernelnote-core.sh"
            target.write_text(source, encoding="utf-8")
            original_argv = module.sys.argv
            try:
                module.sys.argv = [str(SCRIPT), str(target)]
                with self.assertRaises(SystemExit):
                    module.main()
            finally:
                module.sys.argv = original_argv


if __name__ == "__main__":
    unittest.main()
