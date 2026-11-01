#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINALIZER_PATH = ROOT / "scripts/finalize-bore-stable-port.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bore_finalizer_rc_subject", FINALIZER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


finalizer = load_module()


class BoreStableRcSubjectTests(unittest.TestCase):
    def make_lock(self, directory: Path, subject: str) -> Path:
        resolved = directory / ".resolved-patches"
        patch = resolved / "files/01-bore.patch"
        patch.parent.mkdir(parents=True)
        data = (
            "From 1 Mon Sep 17 00:00:00 2001\n"
            f"{subject}\n\n"
            "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c\n"
            "+#define SCHED_BORE_VERSION  \"6.8.0\"\n"
            "+sched_bore\n"
        ).encode()
        patch.write_bytes(data)
        lock = {
            "schema": 1,
            "kernel": {"version": "7.2", "series": "7.2"},
            "components": {
                "bore": {
                    "kind": "git_patch",
                    "selection": "exact",
                    "kernel_target": "7.2",
                    "project_version": "6.8.0",
                    "output": "files/01-bore.patch",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            },
        }
        lock_path = resolved / "patch-lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        return lock_path

    def test_exact_72_rc1_upstream_subject_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = self.make_lock(
                Path(directory), "Subject: [PATCH] linux7.2-rc1-bore-6.8.0"
            )
            record, patch = finalizer.load_locked_bore(lock_path, "7.2")
            self.assertEqual(record["kernel_target"], "7.2")
            self.assertEqual(patch.name, "01-bore.patch")

    def test_unrelated_rc_subject_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = self.make_lock(
                Path(directory), "Subject: [PATCH] linux7.3-rc1-bore-6.8.0"
            )
            with self.assertRaisesRegex(
                finalizer.FinalizeError, "subject does not match"
            ):
                finalizer.load_locked_bore(lock_path, "7.2")

    def test_wrong_bore_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = self.make_lock(
                Path(directory), "Subject: [PATCH] linux7.2-rc1-bore-6.7.0"
            )
            with self.assertRaisesRegex(
                finalizer.FinalizeError, "subject does not match"
            ):
                finalizer.load_locked_bore(lock_path, "7.2")

    def test_reviewed_futex_adapter_only_changes_one_preimage(self) -> None:
        source = "Subject: [PATCH] test\n \t\tif (!timeout || timeout->task)\n"
        adapted = finalizer._rewrite_linux74_futex_context(source)
        self.assertIn("hrtimer_sleeper_task_get(timeout)", adapted)
        self.assertNotIn("timeout->task", adapted)
        with self.assertRaisesRegex(finalizer.FinalizeError, "preimage differs"):
            finalizer._rewrite_linux74_futex_context(adapted)

    def test_cross_series_bore_requires_exact_reviewed_sha(self) -> None:
        record = {"selection": "fallback", "kernel_target": "7.3-rc2",
                  "project_version": "7.0.0", "sha256": "0" * 64,
                  "selected_path": "patches/stable/0001-linux7.3-rc2-bore-7.0.0.patch"}
        self.assertFalse(finalizer._reviewed_linux74_bore(record, "7.4-rc1"))
        record["sha256"] = finalizer.LINUX_74_BORE_BASE_SHA256
        self.assertTrue(finalizer._reviewed_linux74_bore(record, "7.4-rc1"))
        self.assertFalse(finalizer._reviewed_linux74_bore(record, "7.4-rc2"))


if __name__ == "__main__":
    unittest.main()
