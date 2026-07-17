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


def patch(subject: str) -> str:
    return (
        f"From {'1' * 40} Mon Sep 17 00:00:00 2001\n"
        f"Subject: [PATCH] {subject}\n\n"
        "diff --git a/marker.c b/marker.c\n"
        "--- a/marker.c\n"
        "+++ b/marker.c\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )


class GitSymlinkTests(unittest.TestCase):
    def test_repository_relative_patch_symlink_is_followed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            run("git", "init", "-q", "-b", "main", cwd=repo)
            run("git", "config", "user.email", "test@example.invalid", cwd=repo)
            run("git", "config", "user.name", "Test", cwd=repo)
            target = repo / "patches/7.0/clear.patch"
            target.parent.mkdir(parents=True)
            target.write_text(patch("clear target"), encoding="utf-8")
            link = repo / "patches/7.1/clear.patch"
            link.parent.mkdir(parents=True)
            link.symlink_to("../7.0/clear.patch")
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
                        "fallback_globs": ["patches/*/clear.patch"],
                        "require_exact_series": False,
                        "output": "clear.patch",
                    }
                },
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "resolved"
            run(
                "python3", str(RESOLVER),
                "--manifest", str(manifest_path),
                "--output-dir", str(output),
                "--kernel-version", "7.1.3",
                "--kernel-series", "7.1",
            )
            record = json.loads((output / "patch-lock.json").read_text())["components"]["clear"]
            self.assertEqual(record["selected_path"], "patches/7.1/clear.patch")
            self.assertEqual(record["path"], "patches/7.0/clear.patch")
            self.assertIn("clear target", (output / "files/clear.patch").read_text())


if __name__ == "__main__":
    unittest.main()
