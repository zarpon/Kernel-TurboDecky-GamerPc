#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/port-lru-marie-latest.py"
SPEC = importlib.util.spec_from_file_location("port_lru_marie_latest", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LatestMariePortTests(unittest.TestCase):
    def write_fixture(
        self, patch: str, folio: str
    ) -> tuple[Path, Path, tempfile.TemporaryDirectory[str]]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        patch_path = root / "marie.patch"
        folio_path = root / "folio.c"
        patch_path.write_text(patch, encoding="utf-8")
        folio_path.write_text(folio, encoding="utf-8")
        return patch_path, folio_path, tmp

    def test_ports_only_the_reviewed_kvm_types_context(self) -> None:
        patch, folio, tmp = self.write_fixture(
            MODULE.UPSTREAM_HUNK, MODULE.PORTED_CONTEXT
        )
        with tmp:
            self.assertEqual(
                MODULE.adapt(patch, folio),
                "ported-linux-7.3-kvm-types-context",
            )
            self.assertEqual(
                patch.read_text(encoding="utf-8"), MODULE.PORTED_HUNK
            )

    def test_keeps_native_rc1_context_unmodified(self) -> None:
        patch, folio, tmp = self.write_fixture(
            MODULE.UPSTREAM_HUNK, MODULE.UPSTREAM_CONTEXT
        )
        with tmp:
            before = patch.read_bytes()
            self.assertEqual(
                MODULE.adapt(patch, folio), "upstream-hunk-compatible"
            )
            self.assertEqual(patch.read_bytes(), before)

    def test_keeps_native_rc7_hunk_unmodified(self) -> None:
        patch, folio, tmp = self.write_fixture(
            MODULE.NATIVE_RC7_HUNK, MODULE.PORTED_CONTEXT
        )
        with tmp:
            before = patch.read_bytes()
            self.assertEqual(
                MODULE.adapt(patch, folio),
                "native-linux-7.3-rc7-hunk-compatible",
            )
            self.assertEqual(patch.read_bytes(), before)

    def test_native_rc7_hunk_rejects_unknown_target_context(self) -> None:
        patch, folio, tmp = self.write_fixture(
            MODULE.NATIVE_RC7_HUNK, "unknown\n"
        )
        with tmp:
            with self.assertRaisesRegex(MODULE.PortError, "native Linux 7.3-rc7"):
                MODULE.adapt(patch, folio)

    def test_native_rc7_hunk_passes_git_apply_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "mm").mkdir()
            (root / "mm/folio.c").write_text(
                "".join(f"/* filler {index} */\n" for index in range(32))
                + MODULE.PORTED_CONTEXT,
                encoding="utf-8",
            )
            patch = root / "marie.patch"
            patch.write_text(
                "diff --git a/mm/folio.c b/mm/folio.c\n"
                "--- a/mm/folio.c\n"
                "+++ b/mm/folio.c\n"
                + MODULE.NATIVE_RC7_HUNK,
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "apply", "--check", str(patch)], cwd=root, check=True)
            subprocess.run(["git", "apply", str(patch)], cwd=root, check=True)
            subprocess.run(["git", "diff", "--check"], cwd=root, check=True)
            self.assertEqual(
                (root / "mm/folio.c").read_text(encoding="utf-8").count(
                    "#include <linux/lru_marie.h>"
                ),
                1,
            )

    def test_is_idempotent_after_port(self) -> None:
        patch, folio, tmp = self.write_fixture(
            MODULE.PORTED_HUNK, MODULE.PORTED_CONTEXT
        )
        with tmp:
            self.assertEqual(MODULE.adapt(patch, folio), "already-ported")

    def test_unknown_source_context_fails_closed(self) -> None:
        patch, folio, tmp = self.write_fixture(MODULE.UPSTREAM_HUNK, "unknown\n")
        with tmp:
            with self.assertRaisesRegex(MODULE.PortError, "neither the reviewed"):
                MODULE.adapt(patch, folio)

    def test_changed_patch_hunk_fails_closed(self) -> None:
        patch, folio, tmp = self.write_fixture("different\n", MODULE.PORTED_CONTEXT)
        with tmp:
            with self.assertRaisesRegex(MODULE.PortError, "upstream=0"):
                MODULE.adapt(patch, folio)


if __name__ == "__main__":
    unittest.main()
