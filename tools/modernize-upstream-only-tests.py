#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = "__DYNAMIC_PATCH_LOCK_REQUIRED__"


def replace_value_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one old value, found {count}")
    return text.replace(old, new, 1)


def patch_dynamic_fixture() -> None:
    path = ROOT / "tests/test_dynamic_patch_resolver.py"
    text = path.read_text(encoding="utf-8")
    text = replace_value_once(
        text,
        '"https://example.invalid/{output}"',
        '"__DYNAMIC_PATCH_LOCK_REQUIRED__:{name}"',
        "requested lock fixture",
    )
    text = replace_value_once(
        text,
        'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"',
        'NAP_PATCH="$PATCHDIR/0006-nap-current-port.patch"',
        "NAP fixture path",
    )
    version_anchor = "PATCH_ZRAM_IR_VERSION=\\\"__DYNAMIC_PATCH_LOCK_REQUIRED__\\\""
    if version_anchor not in text:
        anchor = "                'NAP_PATCH=\"$PATCHDIR/0006-nap-current-port.patch\"\\n'\n"
        if text.count(anchor) != 1:
            raise SystemExit(f"strict wrapper version fixture anchor count={text.count(anchor)}")
        addition = (
            anchor
            + f"                'PATCH_ZRAM_IR_VERSION=\"{LOCK}\"\\n'\n"
            + f"                'PATCH_POC_VERSION=\"{LOCK}\"\\n'\n"
            + f"                'PATCH_NAP_VERSION=\"{LOCK}\"\\n'\n"
        )
        text = text.replace(anchor, addition, 1)
    assertion = '            self.assertNotIn("https://example.invalid/", first_core)\n'
    if assertion not in text:
        anchor = '            self.assertIn("file://$RESOLVED_PATCH_ROOT/files/08-c23-libbpf.patch", first_core)\n'
        if text.count(anchor) != 1:
            raise SystemExit("lock-only fixture assertion anchor missing")
        text = text.replace(anchor, anchor + assertion, 1)
    path.write_text(text, encoding="utf-8")


def patch_zen_test() -> None:
    path = ROOT / "tests/test_zen_interactive_rewriter.py"
    text = path.read_text(encoding="utf-8")
    new_pair = (
        "'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256='\n"
        "            '\"__DYNAMIC_PATCH_LOCK_REQUIRED__\"'"
    )
    if new_pair not in text:
        old_pair = (
            "'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256='\n"
            "            '\"cdf138cdb94fcb4e2988bd7d2873a51522fdb7212ec314fde202facaf8210b5c\"'"
        )
        if text.count(old_pair) != 1:
            raise SystemExit(f"Zen digest test anchor count={text.count(old_pair)}")
        text = text.replace(old_pair, new_pair, 1)
        path.write_text(text, encoding="utf-8")


def rewrite_bore_test() -> None:
    path = ROOT / "tests/test_bore_port.py"
    content = r'''#!/usr/bin/env python3
"""Contract checks for the current dynamic BORE and sched_ext build path."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "scripts/build-kernelnote-core.sh"
WRAPPER = ROOT / "scripts/build-kernelnote.sh"
MANIFEST = ROOT / "config/patch-sources.json"
FINALIZER = ROOT / "scripts/finalize-bore-stable-port.py"
FINALIZER_BASE = ROOT / "scripts/finalize-bore-stable-port-base.py"
LOCK = "__DYNAMIC_PATCH_LOCK_REQUIRED__"


class BoreLinuxPortTests(unittest.TestCase):
    def test_build_defers_bore_to_the_exact_dynamic_lock(self) -> None:
        core = CORE.read_text(encoding="utf-8")
        finalizer = FINALIZER.read_text(encoding="utf-8") + FINALIZER_BASE.read_text(encoding="utf-8")
        self.assertIn(f'BORE_REPO="{LOCK}"', core)
        self.assertIn(f'BORE_COMMIT="{LOCK}"', core)
        self.assertIn(f'BORE_PATCH_PATH="{LOCK}"', core)
        self.assertIn(f'BORE_PORT_VERSION="{LOCK}"', core)
        self.assertIn("load_locked_bore", finalizer)
        self.assertNotIn("6.8.0-rc1", finalizer)
        self.assertIn('apply_bore_patch "$BORE_PATCH"', core)
        function = core.split("apply_bore_patch() {", 1)[1].split("apply_adios_patch() {", 1)[0]
        self.assertIn("--dry-run", function)
        self.assertNotIn("--fuzz", function)

    def test_sched_ext_coexistence_is_lock_only_and_applied_after_bore(self) -> None:
        core = CORE.read_text(encoding="utf-8")
        self.assertIn(f'BORE_SCHED_EXT_REPO="{LOCK}"', core)
        self.assertIn(f'BORE_SCHED_EXT_COMMIT="{LOCK}"', core)
        self.assertIn(f'BORE_SCHED_EXT_PATCH_PATH="{LOCK}"', core)
        self.assertIn(f'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="{LOCK}"', core)
        self.assertLess(
            core.index('apply_bore_patch "$BORE_PATCH"'),
            core.index('apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"'),
        )
        function = core.split("apply_bore_sched_ext_coexistence_fix() {", 1)[1].split("apply_adios_patch() {", 1)[0]
        self.assertIn("--dry-run", function)
        self.assertNotIn("--fuzz", function)
        self.assertIn("include/linux/sched/bore.h", function)
        wrapper = WRAPPER.read_text(encoding="utf-8")
        shared_anchor = (
            'apply_marie_testing_patch "$MARIE_PATCH"\n'
            'apply_bore_patch "$BORE_PATCH"\n'
            'apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"\n'
            'apply_adios_patch "$PATCHDIR/0003-adios-current.patch"\n'
        )
        self.assertIn(shared_anchor, core)
        self.assertIn(shared_anchor, wrapper)
        self.assertIn(
            'apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"\n'
            'apply_poc_patch "$POC_PATCH"',
            wrapper,
        )

    def test_dynamic_manifest_resolves_current_bore_and_sched_ext(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["components"]
        bore = manifest["bore"]
        self.assertEqual(bore["repo"], "https://github.com/firelzrd/bore-scheduler.git")
        self.assertEqual(bore["ref"], "main")
        self.assertTrue(bore["require_exact_series"])
        self.assertEqual(bore["output"], "01-bore.patch")
        self.assertEqual(
            bore["exact_globs"],
            [
                "patches/testing/0001-linux{series}*-bore-*.patch",
                "patches/stable/linux-{series}-bore/0001-linux{series}*-bore-*.patch",
            ],
        )
        self.assertEqual(
            bore["project_version_regex"],
            r"bore[-_]?([0-9]+(?:\.[0-9]+)+(?:-rc[0-9]+)?)",
        )
        self.assertNotIn("approved_sha256", bore)
        sched_ext = manifest["bore_sched_ext_coexistence"]
        self.assertEqual(sched_ext["repo"], "https://github.com/firelzrd/bore-scheduler.git")
        self.assertEqual(sched_ext["ref"], "main")
        self.assertEqual(sched_ext["output"], "01-bore-sched-ext-coexistence-fix.patch")
        self.assertEqual(sched_ext["exact_globs"], ["patches/additions/0002-sched-ext-coexistence-fix.patch"])


if __name__ == "__main__":
    unittest.main()
'''
    path.write_text(content, encoding="utf-8")


def main() -> None:
    patch_dynamic_fixture()
    patch_zen_test()
    rewrite_bore_test()


if __name__ == "__main__":
    main()
