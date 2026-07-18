#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REWRITER = ROOT / "scripts/apply-known-warning-fixes.py"


class KnownWarningRewriteTests(unittest.TestCase):
    def test_injects_source_and_config_warning_fixes_idempotently(self) -> None:
        fixture = """#!/usr/bin/env bash
normalize_changed_whitespace() {
  :
}
apply_requested_patch_series

# Generic amd64 profile: keep the upstream platform, topology and driver
configure_builtin_cmdline

# PR validation exercises the complete built-in kernel
assert_config \"CONFIG_CMDLINE_BOOL=y\"
"""
        with tempfile.TemporaryDirectory() as directory:
            core = Path(directory) / "core.sh"
            core.write_text(fixture, encoding="utf-8")
            subprocess.run([sys.executable, str(REWRITER), str(core)], check=True)
            first = core.read_text(encoding="utf-8")
            subprocess.run([sys.executable, str(REWRITER), str(core)], check=True)
            second = core.read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertIn("fix_known_build_warnings()", first)
        self.assertIn("static int futex_opcode_31(", first)
        self.assertIn("fix_known_build_warnings\n\n# Generic amd64 profile", first)
        self.assertIn("scripts/config --enable MULTIPLEXER", first)
        self.assertIn('assert_config "CONFIG_MULTIPLEXER=y"', first)


if __name__ == "__main__":
    unittest.main()
