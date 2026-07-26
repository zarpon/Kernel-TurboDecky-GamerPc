#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/update-marie-fallback.py"
SPEC = importlib.util.spec_from_file_location("marie_fallback_updater", MODULE_PATH)
assert SPEC and SPEC.loader
updater = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = updater
SPEC.loader.exec_module(updater)


class MarieFallbackUpdaterTest(unittest.TestCase):
    def test_core_defaults_are_updated_idempotently(self) -> None:
        fixture = '''MARIE_COMMIT="old"
MARIE_PATCH_PATH="patches/testing/old.patch"
MARIE_PATCH="$PATCHDIR/old.patch"
PATCH_MARIE_VERSION="${PATCH_MARIE_VERSION:-0.1.0}"
'''
        record = {
            "commit": "a" * 40,
            "path": "patches/testing/0001-linux7.1-rc5-lru_marie-0.9.0.patch",
            "project_version": "0.9.0",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.sh"
            path.write_text(fixture, encoding="utf-8")
            self.assertTrue(updater.rewrite_core_defaults(path, record))
            first = path.read_text(encoding="utf-8")
            self.assertFalse(updater.rewrite_core_defaults(path, record))
            second = path.read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertIn(f'MARIE_COMMIT="{"a" * 40}"', first)
        self.assertIn(
            'MARIE_PATCH_PATH="patches/testing/0001-linux7.1-rc5-lru_marie-0.9.0.patch"',
            first,
        )
        self.assertIn('MARIE_PATCH="$PATCHDIR/02-lru-marie.patch"', first)
        self.assertIn(
            'PATCH_MARIE_VERSION="${PATCH_MARIE_VERSION:-0.9.0}"', first
        )

    def test_metadata_has_no_time_dependent_fields(self) -> None:
        record = {
            "repo": "repo",
            "ref": "main",
            "commit": "b" * 40,
            "selected_path": "patches/testing/marie-1.0.0.patch",
            "path": "patches/testing/marie-1.0.0.patch",
            "selection": "exact",
            "kernel_target": "7.1",
            "project_version": "1.0.0",
            "sha256": "c" * 64,
            "size": 123,
        }
        metadata = updater.build_metadata(record, "7.1.5", "7.1")
        self.assertNotIn("generated_at", metadata)
        self.assertEqual(metadata["project_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
