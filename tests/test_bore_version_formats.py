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

    def test_release_candidate_is_rejected_as_final_kernel(self) -> None:
        with self.assertRaises(finalizer.FinalizeError):
            finalizer.version_tuple("8.1-rc1", "kernel")

    def test_bore_rc_subject_is_authenticated_for_final_series(self) -> None:
        patch = (
            "From 1 Mon Sep 17 00:00:00 2001\n"
            "Subject: [PATCH] linux7.2-rc1-bore-6.8.0\n"
        )
        target = finalizer.bore_subject_target(patch, "6.8.0")
        self.assertEqual(target, "7.2-rc1")
        self.assertEqual(finalizer.final_target_from_bore_subject(target), "7.2")

    def test_bore_subject_project_version_must_match_lock(self) -> None:
        patch = "Subject: [PATCH] linux7.2-rc1-bore-6.8.0\n"
        with self.assertRaises(finalizer.FinalizeError):
            finalizer.bore_subject_target(patch, "6.7.0")


if __name__ == "__main__":
    unittest.main()
