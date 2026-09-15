#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = "__DYNAMIC_PATCH_LOCK_REQUIRED__"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_dynamic_fixture() -> None:
    path = ROOT / "tests/test_dynamic_patch_resolver.py"
    old = '''            requested_calls = "".join(\n                f'  "$REQUESTED_SERIES_DIR/{output}" "{prefix}" \\\\\n    "https://example.invalid/{output}"\\n'\n'''
    new = '''            requested_calls = "".join(\n                f'  "$REQUESTED_SERIES_DIR/{output}" "{prefix}" \\\\\n    "__DYNAMIC_PATCH_LOCK_REQUIRED__:{name}"\\n'\n'''
    replace_once(path, old, new, "requested lock fixture")

    old_wrapper = '''                'NAP_REPO="old"\\nNAP_COMMIT="old"\\nNAP_PATCH_PATH="old"\\n'\n                'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"\\n'\n                'VRAM_PATCH_REPO="old"\\nVRAM_PATCH_COMMIT="old"\\nVRAM_PATCH_PATH="old"\\n',\n'''
    new_wrapper = f'''                'NAP_REPO="old"\\nNAP_COMMIT="old"\\nNAP_PATCH_PATH="old"\\n'\n                'NAP_PATCH="$PATCHDIR/0006-nap-current-port.patch"\\n'\n                'PATCH_ZRAM_IR_VERSION="{LOCK}"\\n'\n                'PATCH_POC_VERSION="{LOCK}"\\n'\n                'PATCH_NAP_VERSION="{LOCK}"\\n'\n                'VRAM_PATCH_REPO="old"\\nVRAM_PATCH_COMMIT="old"\\nVRAM_PATCH_PATH="old"\\n',\n'''
    replace_once(path, old_wrapper, new_wrapper, "strict wrapper version fixture")

    text = path.read_text(encoding="utf-8")
    assertion = '            self.assertNotIn("https://example.invalid/", first_core)\n'
    anchor = '            self.assertIn("file://$RESOLVED_PATCH_ROOT/files/08-c23-libbpf.patch", first_core)\n'
    if assertion not in text:
        if text.count(anchor) != 1:
            raise SystemExit("lock-only fixture assertion anchor missing")
        text = text.replace(anchor, anchor + assertion, 1)
        path.write_text(text, encoding="utf-8")


def patch_zen_test() -> None:
    path = ROOT / "tests/test_zen_interactive_rewriter.py"
    old = '''        original = original.replace(\n            'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256='\n            '"cdf138cdb94fcb4e2988bd7d2873a51522fdb7212ec314fde202facaf8210b5c"',\n            'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="new-lock-digest"',\n            1,\n        )\n'''
    new = '''        original = original.replace(\n            'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256='\n            '"__DYNAMIC_PATCH_LOCK_REQUIRED__"',\n            'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="new-lock-digest"',\n            1,\n        )\n'''
    replace_once(path, old, new, "Zen digest sentinel test")


def rewrite_bore_test() -> None:
    path = ROOT / "tests/test_bore_port.py"
    path.write_text('''#!/usr/bin/env python3\n"""Contract checks for the current dynamic BORE and sched_ext build path."""\n\nfrom __future__ import annotations\n\nimport json\nimport unittest\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\nCORE = ROOT / "scripts/build-kernelnote-core.sh"\nWRAPPER = ROOT / "scripts/build-kernelnote.sh"\nMANIFEST = ROOT / "config/patch-sources.json"\nFINALIZER = ROOT / "scripts/finalize-bore-stable-port.py"\nFINALIZER_BASE = ROOT / "scripts/finalize-bore-stable-port-base.py"\nLOCK = "__DYNAMIC_PATCH_LOCK_REQUIRED__"\n\n\nclass BoreLinuxPortTests(unittest.TestCase):\n    def test_build_defers_bore_to_the_exact_dynamic_lock(self) -> None:\n        core = CORE.read_text(encoding="utf-8")\n        finalizer = FINALIZER.read_text(encoding="utf-8") + FINALIZER_BASE.read_text(\n            encoding="utf-8"\n        )\n        self.assertIn(f'BORE_REPO="{LOCK}"', core)\n        self.assertIn(f'BORE_COMMIT="{LOCK}"', core)\n        self.assertIn(f'BORE_PATCH_PATH="{LOCK}"', core)\n        self.assertIn(f'BORE_PORT_VERSION="{LOCK}"', core)\n        self.assertIn("load_locked_bore", finalizer)\n        self.assertIn('BORE_PATCH="$RESOLVED_PATCH_ROOT/{output}"', finalizer)\n        self.assertNotIn("6.8.0-rc1", finalizer)\n        self.assertIn('apply_bore_patch "$BORE_PATCH"', core)\n        function = core.split("apply_bore_patch() {", 1)[1].split("apply_adios_patch() {", 1)[0]\n        self.assertIn("--dry-run", function)\n        self.assertNotIn("--fuzz", function)\n\n    def test_sched_ext_coexistence_is_lock_only_and_applied_after_bore(self) -> None:\n        core = CORE.read_text(encoding="utf-8")\n        self.assertIn(f'BORE_SCHED_EXT_REPO="{LOCK}"', core)\n        self.assertIn(f'BORE_SCHED_EXT_COMMIT="{LOCK}"', core)\n        self.assertIn(f'BORE_SCHED_EXT_PATCH_PATH="{LOCK}"', core)\n        self.assertIn(f'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="{LOCK}"', core)\n        self.assertIn(\n            'apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"',\n            core,\n        )\n        self.assertLess(\n            core.index('apply_bore_patch "$BORE_PATCH"'),\n            core.index('apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"'),\n        )\n        function = core.split(\n            "apply_bore_sched_ext_coexistence_fix() {", 1\n        )[1].split("apply_adios_patch() {", 1)[0]\n        self.assertIn("--dry-run", function)\n        self.assertNotIn("--fuzz", function)\n        self.assertIn("include/linux/sched/bore.h", function)\n\n        wrapper = WRAPPER.read_text(encoding="utf-8")\n        shared_anchor = '''apply_marie_testing_patch "$MARIE_PATCH"\napply_bore_patch "$BORE_PATCH"\napply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"\napply_adios_patch "$PATCHDIR/0003-adios-current.patch"\n'''\n        self.assertIn(shared_anchor, core)\n        self.assertIn(shared_anchor, wrapper)\n        self.assertIn(\n            'apply_bore_sched_ext_coexistence_fix "$BORE_SCHED_EXT_PATCH"\\n'\n            'apply_poc_patch "$POC_PATCH"',\n            wrapper,\n        )\n\n    def test_dynamic_manifest_resolves_current_bore_and_sched_ext(self) -> None:\n        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["components"]\n        bore = manifest["bore"]\n        self.assertEqual(bore["repo"], "https://github.com/firelzrd/bore-scheduler.git")\n        self.assertEqual(bore["ref"], "main")\n        self.assertTrue(bore["require_exact_series"])\n        self.assertEqual(bore["output"], "01-bore.patch")\n        self.assertEqual(\n            bore["exact_globs"],\n            [\n                "patches/testing/0001-linux{series}*-bore-*.patch",\n                "patches/stable/linux-{series}-bore/0001-linux{series}*-bore-*.patch",\n            ],\n        )\n        self.assertEqual(\n            bore["project_version_regex"],\n            r"bore[-_]?([0-9]+(?:\\.[0-9]+)+(?:-rc[0-9]+)?)",\n        )\n        self.assertNotIn("approved_sha256", bore)\n\n        sched_ext = manifest["bore_sched_ext_coexistence"]\n        self.assertEqual(sched_ext["repo"], "https://github.com/firelzrd/bore-scheduler.git")\n        self.assertEqual(sched_ext["ref"], "main")\n        self.assertEqual(sched_ext["output"], "01-bore-sched-ext-coexistence-fix.patch")\n        self.assertEqual(\n            sched_ext["exact_globs"],\n            ["patches/additions/0002-sched-ext-coexistence-fix.patch"],\n        )\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")


def main() -> None:
    patch_dynamic_fixture()
    patch_zen_test()
    rewrite_bore_test()


if __name__ == "__main__":
    main()
