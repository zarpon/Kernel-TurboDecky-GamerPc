#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts/resolve-patch-sources.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


def patch(subject: str, body: str) -> str:
    return (
        f"From {'1' * 40} Mon Sep 17 00:00:00 2001\n"
        f"Subject: [PATCH] {subject}\n\n"
        "diff --git a/lz4kdr.c b/lz4kdr.c\n"
        "--- a/lz4kdr.c\n"
        "+++ b/lz4kdr.c\n"
        "@@ -1 +1 @@\n-old\n+new\n\n"
        f"{body}\n"
    )


def init_repo(path: Path, files: dict[str, str]) -> str:
    path.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=path)
    run("git", "config", "user.email", "test@example.invalid", cwd=path)
    run("git", "config", "user.name", "Test", cwd=path)
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run("git", "add", ".", cwd=path)
    run("git", "commit", "-qm", "fixture", cwd=path)
    return run("git", "rev-parse", "HEAD", cwd=path).stdout.strip()


class Lz4kdrResolverTests(unittest.TestCase):
    def test_upstream_then_reviewed_port_and_local_zswap_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            repo = tmp / "upstream"
            official_path = "patches/0001-linux6.12.74-lz4kdr-1.3.patch"
            official = patch(
                "linux6.12.74-lz4kdr-1.3",
                "ZRAM_BACKEND_LZ4KDR ZRAM_DEF_COMP_LZ4KDR lz4kdr_encode",
            )
            commit = init_repo(repo, {official_path: official})

            port_path = tmp / "ports/7.1.5-lz4kdr.patch"
            port = patch(
                "linux7.1.5-lz4kdr-1.3-port",
                "ZRAM_BACKEND_LZ4KDR ZRAM_DEF_COMP_LZ4KDR lz4kdr_encode",
            )
            port_path.parent.mkdir(parents=True)
            port_path.write_text(port, encoding="utf-8")
            port_metadata = {
                "schema": 1,
                "component": "lz4kdr",
                "kernel_target": "7.1.5",
                "project_version": "1.3",
                "upstream_repository": str(repo),
                "upstream_ref": "main",
                "upstream_commit": commit,
                "upstream_path": official_path,
                "upstream_sha256": hashlib.sha256(official.encode()).hexdigest(),
                "sha256": hashlib.sha256(port.encode()).hexdigest(),
                "size": len(port.encode()),
            }
            (tmp / "ports/7.1.5-lz4kdr.json").write_text(
                json.dumps(port_metadata), encoding="utf-8"
            )

            zswap_path = tmp / "ports/7.1.5-lz4kdr-zswap.patch"
            zswap_data = patch(
                "lz4kdr zswap adapter 1.0",
                "CRYPTO_LZ4KDR crypto_register_acomp zswap.compressor=lz4kdr "
                "ZSWAP_COMPRESSOR_DEFAULT_LZ4KDR",
            )
            zswap_path.write_text(zswap_data, encoding="utf-8")
            (tmp / "ports/7.1.5-lz4kdr-zswap.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "component": "lz4kdr_zswap",
                        "kernel_target": "7.1.5",
                        "project_version": "1.0",
                        "sha256": hashlib.sha256(zswap_data.encode()).hexdigest(),
                        "size": len(zswap_data.encode()),
                    }
                ),
                encoding="utf-8",
            )

            manifest = {
                "schema": 1,
                "components": {
                    "lz4kdr": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/*linux{series}*lz4kdr*.patch"],
                        "fallback_globs": ["patches/*lz4kdr*.patch"],
                        "require_exact_series": False,
                        "output": "25-lz4kdr.patch",
                        "project_version_regex": r"lz4kdr-([0-9.]+)",
                        "required_markers": [
                            "ZRAM_BACKEND_LZ4KDR",
                            "ZRAM_DEF_COMP_LZ4KDR",
                            "lz4kdr_encode",
                        ],
                        "local_port_patch": "ports/7.1.5-lz4kdr.patch",
                        "local_port_metadata": "ports/7.1.5-lz4kdr.json",
                        "local_port_upstream_sha256": port_metadata["upstream_sha256"],
                    },
                    "lz4kdr_zswap": {
                        "kind": "local_patch",
                        "local_patch": "ports/7.1.5-lz4kdr-zswap.patch",
                        "local_metadata": "ports/7.1.5-lz4kdr-zswap.json",
                        "output": "26-lz4kdr-zswap.patch",
                        "required_markers": [
                            "CRYPTO_LZ4KDR",
                            "crypto_register_acomp",
                            "zswap.compressor=lz4kdr",
                            "ZSWAP_COMPRESSOR_DEFAULT_LZ4KDR",
                        ],
                    },
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = tmp / "resolved"
            run(
                "python3", str(RESOLVER), "--manifest", str(manifest_path),
                "--output-dir", str(output), "--kernel-version", "7.1.5",
                "--kernel-series", "7.1",
            )

            lock = json.loads((output / "patch-lock.json").read_text(encoding="utf-8"))
            lz4kdr = lock["components"]["lz4kdr"]
            self.assertEqual(lz4kdr["selection"], "upstream-port")
            self.assertEqual(lz4kdr["origin"], "local-port")
            self.assertEqual(lz4kdr["upstream"]["path"], official_path)
            self.assertEqual(lz4kdr["upstream"]["commit"], commit)
            self.assertEqual(lz4kdr["sha256"], port_metadata["sha256"])
            self.assertEqual(
                (output / "files/25-lz4kdr.patch").read_text(encoding="utf-8"), port
            )

            zswap = lock["components"]["lz4kdr_zswap"]
            self.assertEqual(zswap["selection"], "local-port")
            self.assertEqual(zswap["kernel_target"], "7.1.5")
            self.assertEqual(
                (output / "files/26-lz4kdr-zswap.patch").read_text(encoding="utf-8"),
                zswap_data,
            )

    def test_changed_upstream_rejects_stale_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            repo = tmp / "upstream"
            path = "patches/0001-linux6.12.74-lz4kdr-1.3.patch"
            original = patch("linux6.12.74-lz4kdr-1.3", "ZRAM_BACKEND_LZ4KDR lz4kdr_encode")
            commit = init_repo(repo, {path: original})
            port = patch("linux7.1.5-lz4kdr-1.3-port", "ZRAM_BACKEND_LZ4KDR lz4kdr_encode")
            (tmp / "port.patch").write_text(port, encoding="utf-8")
            (tmp / "port.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "component": "lz4kdr",
                        "kernel_target": "7.1.5",
                        "project_version": "1.3",
                        "upstream_repository": str(repo),
                        "upstream_ref": "main",
                        "upstream_commit": commit,
                        "upstream_path": path,
                        "upstream_sha256": hashlib.sha256(original.encode()).hexdigest(),
                        "sha256": hashlib.sha256(port.encode()).hexdigest(),
                        "size": len(port.encode()),
                    }
                ),
                encoding="utf-8",
            )
            changed = patch("linux6.12.74-lz4kdr-1.3", "changed upstream ZRAM_BACKEND_LZ4KDR lz4kdr_encode")
            (repo / path).write_text(changed, encoding="utf-8")
            run("git", "-C", str(repo), "add", path)
            run("git", "-C", str(repo), "commit", "-qm", "upstream changed")

            manifest = {
                "schema": 1,
                "components": {
                    "lz4kdr": {
                        "kind": "git_patch", "repo": str(repo), "ref": "main",
                        "exact_globs": [], "fallback_globs": ["patches/*lz4kdr*.patch"],
                        "output": "lz4kdr.patch", "required_markers": ["ZRAM_BACKEND_LZ4KDR", "lz4kdr_encode"],
                        "local_port_patch": "port.patch", "local_port_metadata": "port.json",
                        "local_port_upstream_sha256": hashlib.sha256(original.encode()).hexdigest(),
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3", str(RESOLVER), "--manifest", str(manifest_path),
                    "--output-dir", str(tmp / "resolved"), "--kernel-version", "7.1.5",
                    "--kernel-series", "7.1",
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewed local port", result.stderr)


if __name__ == "__main__":
    unittest.main()
