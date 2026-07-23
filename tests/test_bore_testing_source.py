#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/resolve-patch-sources.py"
SPEC = importlib.util.spec_from_file_location("resolve_patch_sources", MODULE_PATH)
assert SPEC and SPEC.loader
resolver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = resolver
SPEC.loader.exec_module(resolver)


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


def patch(subject: str, version: str) -> str:
    return "".join(
        (
            f"From {'4' * 40} Mon Sep 17 00:00:00 2001\n",
            f"Subject: [PATCH] {subject}\n\n",
            "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c\n",
            "--- /dev/null\n",
            "+++ b/kernel/sched/bore.c\n",
            "@@ -0,0 +1,3 @@\n",
            f"+#define SCHED_BORE_VERSION \"{version}\"\n",
            "+#ifdef CONFIG_SCHED_BORE\n",
            "+int sched_bore;\n",
        )
    )


class BoreTestingSourceTests(unittest.TestCase):
    def make_repo(self, root: Path, *, include_71: bool = True) -> Path:
        repo = root / "bore"
        repo.mkdir()
        run("git", "init", "-q", "-b", "main", cwd=repo)
        run("git", "config", "user.email", "test@example.invalid", cwd=repo)
        run("git", "config", "user.name", "Test", cwd=repo)
        testing = repo / "patches/testing"
        testing.mkdir(parents=True)
        if include_71:
            (testing / "0001-linux7.1-rc1-bore-6.8.0-rc1.patch").write_text(
                patch("linux7.1-rc1-bore-6.8.0-rc1", "6.8.0-rc1"), encoding="utf-8"
            )
        (testing / "0001-linux7.2-rc1-bore-6.9.0-rc1.patch").write_text(
            patch("linux7.2-rc1-bore-6.9.0-rc1", "6.9.0-rc1"), encoding="utf-8"
        )
        stable = repo / "patches/stable"
        stable.mkdir()
        (stable / "0001-linux7.1-bore-9.9.9.patch").write_text(
            patch("linux7.1-bore-9.9.9", "9.9.9"), encoding="utf-8"
        )
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "fixture", cwd=repo)
        return repo

    @staticmethod
    def manifest(repo: Path) -> dict[str, object]:
        return {
            "schema": 1,
            "components": {
                "bore": {
                    "kind": "git_patch",
                    "repo": str(repo),
                    "ref": "main",
                    "exact_globs": ["patches/testing/*linux{series}*bore*.patch"],
                    "fallback_globs": [],
                    "require_exact_series": True,
                    "output": "01-bore.patch",
                    "project_version_regex": r"bore[-_]?v?([0-9]+(?:\.[0-9]+)+(?:-rc[0-9]+|r[0-9]+)?)",
                    "required_markers": [
                        "SCHED_BORE_VERSION",
                        "CONFIG_SCHED_BORE",
                        "kernel/sched/bore.c",
                    ],
                }
            },
        }

    def test_selects_exact_71_testing_patch_and_ignores_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            lock = resolver.resolve(
                self.manifest(repo),
                root / "resolved",
                resolver.KernelVersion.parse("7.1.4"),
                "7.1",
            )
            record = lock["components"]["bore"]
            self.assertEqual(record["selection"], "exact")
            self.assertEqual(record["kernel_target"], "7.1")
            self.assertEqual(record["project_version"], "6.8.0-rc1")
            self.assertIn("/testing/", f"/{record['selected_path']}")
            self.assertNotIn("9.9.9", record["selected_path"])
            self.assertEqual(len(record["sha256"]), 64)

    def test_missing_71_testing_patch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root, include_71=False)
            with self.assertRaises(resolver.ResolverError):
                resolver.resolve(
                    self.manifest(repo),
                    root / "resolved",
                    resolver.KernelVersion.parse("7.1.4"),
                    "7.1",
                )

    def test_repository_configuration_enables_bore(self) -> None:
        manifest = json.loads(
            (ROOT / "config/patch-sources.json").read_text(encoding="utf-8")
        )
        self.assertIn("bore", manifest["components"])
        self.assertNotIn("infi" + "nity", manifest["components"])
        config = (ROOT / "config/kernelnote.config").read_text(encoding="utf-8")
        self.assertIn("CONFIG_SCHED_BORE=y", config)


if __name__ == "__main__":
    unittest.main()
