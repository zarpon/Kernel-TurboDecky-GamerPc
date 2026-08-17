#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINALIZER_PATH = ROOT / "scripts/finalize-bore-stable-port.py"
SPEC = importlib.util.spec_from_file_location("finalize_bore_stable_port_versions", FINALIZER_PATH)
assert SPEC and SPEC.loader
finalizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(finalizer)


class BoreVersionFormatTests(unittest.TestCase):
    def test_two_component_final_release(self) -> None:
        self.assertEqual(finalizer.version_tuple("7.2", "kernel"), (7, 2, 0))

    def test_future_two_component_final_release(self) -> None:
        self.assertEqual(finalizer.version_tuple("8.0", "kernel"), (8, 0, 0))

    def test_patchlevel_final_release(self) -> None:
        self.assertEqual(finalizer.version_tuple("8.0.1", "kernel"), (8, 0, 1))

    def test_release_candidate_is_rejected(self) -> None:
        with self.assertRaises(finalizer.FinalizeError):
            finalizer.version_tuple("8.1-rc1", "kernel")


if __name__ == "__main__":
    unittest.main()
