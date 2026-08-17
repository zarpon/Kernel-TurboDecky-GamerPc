#!/usr/bin/env python3
"""Contract checks for the dynamic BORE and sched_ext build path."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHED_EXT_PORT = ROOT / "patches/bore/7.1.4-sched-ext-coexistence-fix.patch"
CORE = ROOT / "scripts/build-kernelnote-core.sh"
WRAPPER = ROOT / "scripts/build-kernelnote.sh"
MANIFEST = ROOT / "config/patch-sources.json"
FINALIZER = ROOT / "scripts/finalize-bore-stable-port.py"
FINALIZER_BASE = ROOT / "scripts/finalize-bore-stable-port-base.py"


class BoreLinuxPortTests(unittest.TestCase):
    def test_build_defers_bore_to_the_exact_dynamic_lock(self) -> None:
        core = CORE.read_text(encoding="utf-8")
        finalizer = FINALIZER.read_text(encoding="utf-8") + FINALIZER_BASE.read_text(
            encoding="utf-8"
        )
        self.assertIn('BORE_REPO="https://github.com/firelzrd/bore-scheduler.git"', core)
        self.assertIn("load_locked_bore", finalizer)
        self.assertIn('BORE_PATCH="$RESOLVED_PATCH_ROOT/{output}"', finalizer)
        self.assertNotIn("6.8.0-rc1", finalizer)
        self.assertIn('apply_bore_patch "$BORE_PATCH"', core)
        function = core.split("apply_bore_patch() {", 1)[1].split("apply_adios_patch() {", 1)[0]
        self.assertIn("--dry-run", function)
        self.assertNotIn("--fuzz", function)

    def test_sched_ext_coexistence_fix_is_pinned_and_applied_after_bore(self) -> None:
        data = SCHED_EXT_PORT.read_bytes()
        self.assertEqual(
            hashlib.sha256(data).hexdigest(),
            "73556222dd3d720f99f353e84f30c858031ada7496bbfc88f96787482dcf5429",
        )
        text = data.decode("utf-8")
        for marker in (
            "Subject: [PATCH] sched: port 0002 sched-ext coexistence fix to Linux 7.1.4",
            "void reweight_task(struct task_struct *p, int prio)",
            "extern void reweight_task(struct task_struct *p, int prio);",
            "Upstream-sha256: cdf138cdb94fcb4e2988bd7d2873a51522fdb7212ec314fde202facaf8210b5c",
        ):
            self.assertIn(marker, text)

        core = CORE.read_text(encoding="utf-8")
        self.assertIn(
            'BORE_SCHED_EXT_PATCH_PATH="patches/additions/0002-sched-ext-coexistence-fix.patch"',
            core,
        )
        self.assertIn(
            'apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"',
            core,
        )
        self.assertLess(
            core.index('apply_bore_patch "$BORE_PATCH"'),
            core.index('apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"'),
        )
        function = core.split(
            "apply_bore_sched_ext_coexistence_fix() {", 1
        )[1].split("apply_adios_patch() {", 1)[0]
        self.assertIn("--dry-run", function)
        self.assertNotIn("--fuzz", function)
        self.assertIn("include/linux/sched/bore.h", function)

        wrapper = WRAPPER.read_text(encoding="utf-8")
        shared_anchor = '''apply_marie_testing_patch "$MARIE_PATCH"
apply_bore_patch "$BORE_PATCH"
apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"
apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"
'''
        self.assertIn(shared_anchor, core)
        self.assertIn(shared_anchor, wrapper)
        self.assertIn(
            'apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"\n'
            'apply_poc_patch "$POC_PATCH"',
            wrapper,
        )

    def test_dynamic_manifest_requires_native_bore_71_source(self) -> None:
        component = json.loads(MANIFEST.read_text(encoding="utf-8"))["components"]["bore"]
        self.assertEqual(component["repo"], "https://github.com/firelzrd/bore-scheduler.git")
        self.assertEqual(component["ref"], "main")
        self.assertTrue(component["require_exact_series"])
        self.assertEqual(component["output"], "01-bore.patch")
        self.assertEqual(
            component["exact_globs"],
            [
                "patches/testing/0001-linux{series}*-bore-*.patch",
                "patches/stable/linux-{series}-bore/0001-linux{series}*-bore-*.patch",
            ],
        )
        self.assertEqual(
            component["project_version_regex"],
            r"bore[-_]?([0-9]+(?:\.[0-9]+)+(?:-rc[0-9]+)?)",
        )
        self.assertNotIn("approved_sha256", component)

        sched_ext = json.loads(MANIFEST.read_text(encoding="utf-8"))[
            "components"
        ]["bore_sched_ext_coexistence"]
        self.assertEqual(sched_ext["repo"], "https://github.com/firelzrd/bore-scheduler.git")
        self.assertEqual(sched_ext["ref"], "main")
        self.assertEqual(sched_ext["output"], "01-bore-sched-ext-coexistence-fix.patch")
        self.assertEqual(
            sched_ext["exact_globs"],
            ["patches/additions/0002-sched-ext-coexistence-fix.patch"],
        )


if __name__ == "__main__":
    unittest.main()
