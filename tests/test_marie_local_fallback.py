#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/resolve-patch-sources.py"
SPEC = importlib.util.spec_from_file_location("resolver_local_fallback", MODULE_PATH)
assert SPEC and SPEC.loader
resolver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = resolver
SPEC.loader.exec_module(resolver)


def sample_patch(version: str = "9.9.9", target: str = "7.1-rc5") -> bytes:
    semantic_version = version.rsplit("r", 1)[0] if version.rsplit("r", 1)[-1].isdigit() and "r" in version else version
    return (
        f"From {'1' * 40} Mon Sep 17 00:00:00 2001\n"
        f"Subject: [PATCH] linux{target}-lru_marie-{semantic_version}\n\n"
        "diff --git a/mm/Kconfig b/mm/Kconfig\n"
        "--- a/mm/Kconfig\n"
        "+++ b/mm/Kconfig\n"
        "@@ -1 +1,2 @@\n"
        " x\n"
        "+config LRU_MARIE\n"
        "+lru_marie\n"
    ).encode()


class MarieLocalFallbackTest(unittest.TestCase):
    def fixture(
        self,
        root: Path,
        version: str = "9.9.9",
        target: str = "7.1-rc5",
    ) -> tuple[dict, Path]:
        config = root / "config"
        fallback = root / "patches/fallback"
        config.mkdir(parents=True)
        fallback.mkdir(parents=True)
        data = sample_patch(version, target)
        (fallback / "lru_marie.patch").write_bytes(data)
        selected = f"patches/testing/0001-linux{target}-lru_marie-{version}.patch"
        target_series = ".".join(target.split("-")[0].split(".")[:2])
        metadata = {
            "schema": 1,
            "repo": "https://example.invalid/lru_marie.git",
            "ref": "main",
            "commit": "2" * 40,
            "selected_path": selected,
            "path": selected,
            "selection": "exact",
            "kernel_target": target,
            "project_version": version,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        (fallback / "lru_marie.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        manifest = {
            "schema": 1,
            "components": {
                "marie": {
                    "kind": "git_patch",
                    "repo": str(root / "missing-upstream.git"),
                    "ref": "main",
                    "exact_globs": [
                        "patches/testing/*linux{series}*lru_marie*.patch"
                    ],
                    "fallback_globs": [],
                    "require_exact_series": False,
                    "output": "02-lru-marie.patch",
                    "project_version_regex": (
                        r"lru[_-]marie[-_]?v?([0-9]+(?:\.[0-9]+)+(?:r[0-9]+)?)"
                    ),
                    "required_markers": ["LRU_MARIE", "lru_marie"],
                    "local_fallback_patch": "../patches/fallback/lru_marie.patch",
                    "local_fallback_metadata": "../patches/fallback/lru_marie.json",
                }
            },
        }
        self.assertEqual(target_series, f"{resolver.KernelVersion.parse(target).series[0]}.{resolver.KernelVersion.parse(target).series[1]}")
        return manifest, config

    def test_uses_valid_local_fallback_when_upstream_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, config = self.fixture(root)
            output = root / "resolved"
            lock = resolver.resolve(
                manifest,
                output,
                resolver.KernelVersion.parse("7.1.5"),
                "7.1",
                manifest_root=config,
            )
            record = lock["components"]["marie"]
            self.assertEqual(record["selection"], "local-fallback")
            self.assertEqual(record["project_version"], "9.9.9")
            self.assertEqual(
                (output / record["output"]).read_bytes(), sample_patch()
            )

    def test_preserves_revision_release_fallback_for_rc_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, config = self.fixture(
                root, version="0.11.1r2", target="7.3-rc1"
            )
            output = root / "resolved"
            lock = resolver.resolve(
                manifest,
                output,
                resolver.KernelVersion.parse("7.3-rc3"),
                "7.3",
                manifest_root=config,
            )
            record = lock["components"]["marie"]
            self.assertEqual(record["selection"], "local-fallback")
            self.assertEqual(record["project_version"], "0.11.1r2")
            self.assertEqual(record["kernel_target"], "7.3-rc1")
            self.assertEqual(
                (output / record["output"]).read_bytes(),
                sample_patch("0.11.1r2", "7.3-rc1"),
            )

    def test_rejects_corrupted_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, config = self.fixture(root)
            (root / "patches/fallback/lru_marie.patch").write_bytes(b"corrupt")
            with self.assertRaises(resolver.ResolverError):
                resolver.resolve(
                    manifest,
                    root / "resolved",
                    resolver.KernelVersion.parse("7.1.5"),
                    "7.1",
                    manifest_root=config,
                )


if __name__ == "__main__":
    unittest.main()
