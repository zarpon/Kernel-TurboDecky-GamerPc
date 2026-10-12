#!/usr/bin/env python3
"""Regression tests for the reviewed Linux 7.3 Marie port."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/port-marie-folio-7.3.py"
SPEC = importlib.util.spec_from_file_location("marie_73_port", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Marie73PortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "mm").mkdir()
        (self.root / "mm/folio.c").write_text(
            MODULE.TARGET_INCLUDE, encoding="utf-8"
        )
        self.upstream = (
            "From abc Mon Sep 17 00:00:00 2001\n" + MODULE.SUBJECT
            + "\n---\n mm/folio.c | 1 +\n\n"
            + "diff --git a/mm/folio.c b/mm/folio.c\n"
            + "index c02dcea9c0..86cfdfd341 100644\n"
            + "--- a/mm/folio.c\n+++ b/mm/folio.c\n"
            + MODULE.ORIGINAL_INCLUDE
            + MODULE.ORIGINAL_LOCALVERSION
            + "diff --git a/mm/other.c b/mm/other.c\n"
            + "--- a/mm/other.c\n+++ b/mm/other.c\n"
            + "@@ -1 +1 @@\n-old\n+new\n"
        )

    def test_reviewed_port_preserves_all_remaining_hunks(self) -> None:
        result = MODULE.port(self.upstream, self.root, "7.3-rc7")
        self.assertEqual(
            result,
            self.upstream.replace(
                MODULE.ORIGINAL_INCLUDE, MODULE.PORTED_INCLUDE, 1
            ).replace(MODULE.ORIGINAL_LOCALVERSION, "", 1),
        )
        self.assertIn("diff --git a/mm/other.c", result)

    def test_newer_kernel_or_drift_fails_closed(self) -> None:
        with self.assertRaises(MODULE.PortError):
            MODULE.port(self.upstream, self.root, "7.4-rc1")
        (self.root / "mm/folio.c").write_text(
            MODULE.TARGET_INCLUDE.replace(
                "#include <linux/kvm_types.h>\n", ""
            ),
            encoding="utf-8",
        )
        with self.assertRaises(MODULE.PortError):
            MODULE.port(self.upstream, self.root, "7.3-rc7")

    def test_upstream_version_or_hunk_drift_fails_closed(self) -> None:
        with self.assertRaises(MODULE.PortError):
            MODULE.port(
                self.upstream.replace(
                    "@@ -33,6 +33,7 @@", "@@ -34,6 +34,7 @@"
                ),
                self.root,
                "7.3-rc7",
            )

    def test_localversion_present_keeps_validated_upstream_deletion(self) -> None:
        (self.root / "localversion").write_text("-marie", encoding="utf-8")
        self.assertIn(
            MODULE.ORIGINAL_LOCALVERSION,
            MODULE.port(self.upstream, self.root, "7.3-rc7"),
        )

    def test_unreviewed_localversion_is_rejected(self) -> None:
        (self.root / "localversion").write_text("-custom", encoding="utf-8")
        with self.assertRaises(MODULE.PortError):
            MODULE.port(self.upstream, self.root, "7.3-rc7")

    def test_ported_73_include_hunk_passes_git_apply_check(self) -> None:
        kernel = self.root
        subprocess.run(["git", "init", "-q"], cwd=kernel, check=True)
        partial_patch = (
            "diff --git a/mm/folio.c b/mm/folio.c\n"
            "--- a/mm/folio.c\n+++ b/mm/folio.c\n"
            + MODULE.PORTED_INCLUDE
        )
        patch = kernel / "include.patch"
        patch.write_text(partial_patch, encoding="utf-8")
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=kernel, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=kernel, check=True)
        subprocess.run(["git", "diff", "--check"], cwd=kernel, check=True)
        self.assertEqual(
            (kernel / "mm/folio.c").read_text(encoding="utf-8").count(
                "#include <linux/lru_marie.h>"
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
