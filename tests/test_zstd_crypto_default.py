#!/usr/bin/env python3
"""Verify the Crypto API ZSTD policy fails closed and never edits ZRAM."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/set-zstd-crypto-default.py"
SPEC = importlib.util.spec_from_file_location("set_zstd_crypto_default", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
BUILD = (ROOT / "scripts/build-kernelnote-core.sh").read_text(encoding="utf-8")
ZRAM = (ROOT / "packaging/90-turbodecky-zram.conf").read_text(encoding="utf-8")
ZRAM_HELPER = (ROOT / "packaging/configure-zram-ir").read_text(encoding="utf-8")


class ZstdCryptoDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "crypto" / "zstd.c"
        self.path.parent.mkdir()

    def test_changes_only_crypto_default_level(self) -> None:
        original = (
            "#include <linux/zstd.h>\n"
            "#define ZSTD_DEF_LEVEL\t\t3\n"
            "#define ZSTD_MAX_WINDOWLOG\t18\n"
            "params = zstd_get_params(ZSTD_DEF_LEVEL, ZSTD_MAX_SIZE);\n"
        )
        self.path.write_text(original, encoding="utf-8")
        MODULE.set_default(self.path)
        self.assertEqual(
            self.path.read_text(encoding="utf-8"),
            original.replace("#define ZSTD_DEF_LEVEL\t\t3", "#define ZSTD_DEF_LEVEL\t\t1"),
        )

    def test_rejects_unexpected_level_without_writing(self) -> None:
        for level in ("1", "2", "4", "ZSTD_DEFAULT_CLEVEL"):
            with self.subTest(level=level):
                original = f"#define ZSTD_DEF_LEVEL {level}\n"
                self.path.write_text(original, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unreviewed override"):
                    MODULE.set_default(self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_rejects_missing_or_duplicate_definitions(self) -> None:
        for original in ("#define NOT_ZSTD 3\n", "#define ZSTD_DEF_LEVEL 3\n#define ZSTD_DEF_LEVEL 3\n"):
            with self.subTest(source=original):
                self.path.write_text(original, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    MODULE.set_default(self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_build_runs_before_patching_and_retains_zram_ir(self) -> None:
        invocation = 'python3 "$ROOT/scripts/set-zstd-crypto-default.py" "$KERNELDIR/crypto/zstd.c"'
        self.assertEqual(BUILD.count(invocation), 1)
        self.assertLess(BUILD.index(invocation), BUILD.index('apply_marie_testing_patch "$MARIE_PATCH"'))
        self.assertIn("compression-algorithm = lz4 zstd", ZRAM)
        self.assertIn("'algo=zstd priority=1'", ZRAM_HELPER)
        self.assertNotIn("ZSTD_DEF_LEVEL", ZRAM + ZRAM_HELPER)


if __name__ == "__main__":
    unittest.main()
