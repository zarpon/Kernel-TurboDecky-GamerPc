#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts/resolve-patch-sources.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


def patch() -> str:
    return (
        f"From {'2' * 40} Mon Sep 17 00:00:00 2001\n"
        "Subject: [PATCH] regular indirection target\n\n"
        "diff --git a/a.c b/a.c\n--- a/a.c\n+++ b/a.c\n@@ -1 +1 @@\n-a\n+b\n"
    )


class RegularIndirectionTests(unittest.TestCase):
    def test_one_line_relative_patch_pointer_is_followed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            run("git", "init", "-q", "-b", "main", cwd=repo)
            run("git", "config", "user.email", "test@example.invalid", cwd=repo)
            run("git", "config", "user.name", "Test", cwd=repo)
            target = repo / "patches/7.0/clear.patch"
            target.parent.mkdir(parents=True)
            target.write_text(patch(), encoding="utf-8")
            pointer = repo / "patches/7.1/clear.patch"
            pointer.parent.mkdir(parents=True)
            pointer.write_text("../7.0/clear.patch\n", encoding="utf-8")
            run("git", "add", ".", cwd=repo)
            run("git", "commit", "-qm", "fixture", cwd=repo)
            manifest = {
                "schema": 1,
                "components": {
                    "clear": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/{series}/clear.patch"],
                        "fallback_globs": [],
                        "require_exact_series": True,
                        "output": "clear.patch",
                    }
                },
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "resolved"
            run(
                "python3", str(RESOLVER), "--manifest", str(manifest_path),
                "--output-dir", str(output), "--kernel-version", "7.1.3",
                "--kernel-series", "7.1",
            )
            record = json.loads((output / "patch-lock.json").read_text())["components"]["clear"]
            self.assertEqual(record["selected_path"], "patches/7.1/clear.patch")
            self.assertEqual(record["path"], "patches/7.0/clear.patch")
            self.assertIn("regular indirection target", (output / "files/clear.patch").read_text())


if __name__ == "__main__":
    unittest.main()
