from __future__ import annotations

import difflib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ath11k_rekey_fix", ROOT / "scripts/apply-ath11k-rekey-fix.py")
fix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fix)

CORE_BEFORE = "struct ath11k_vif {\n};\n"
CORE = "struct ath11k_vif {\n u32 num_stations;\n bool reinstall_group_keys;\n};\n"
INSTALL = """static int ath11k_install_key(void)
{
 if (cmd == DISABLE_KEY) {
  arg.key_cipher = WMI_CIPHER_NONE;
  arg.key_data = NULL;
  goto install;
 }
install:
 return 0;
}
"""
MAC = INSTALL + """
static int ath11k_set_group_keys(void)
{
 if (!key || (key->flags & IEEE80211_KEY_FLAG_PAIRWISE))
  continue;
 return ath11k_install_key(arvif, key, SET_KEY, addr, WMI_KEY_GROUP);
}
static int ath11k_mac_inc_num_stations(void) { arvif->num_stations++; }
static void ath11k_mac_dec_num_stations(void) { arvif->num_stations--; }
static int ath11k_mac_station_add(void)
{
 if (arvif->num_stations == 1 && arvif->reinstall_group_keys) {
  ret = ath11k_set_group_keys(arvif);
  arvif->reinstall_group_keys = false;
 }
}
static int ath11k_mac_op_set_key(void)
{
 if (key->flags & IEEE80211_KEY_FLAG_PAIRWISE)
  flags = WMI_KEY_PAIRWISE;
 else
  flags = WMI_KEY_GROUP;
 is_ap_with_no_sta = (vif->type == NL80211_IFTYPE_AP && !arvif->num_stations);
 if (flags == WMI_KEY_PAIRWISE || cmd == SET_KEY || is_ap_with_no_sta) {
  ret = ath11k_install_key(arvif, key, cmd, peer_addr, flags);
  ret = ath11k_dp_peer_rx_pn_replay_config(arvif, peer_addr, cmd, key);
  if (flags == WMI_KEY_GROUP && cmd == SET_KEY && is_ap_with_no_sta)
   arvif->reinstall_group_keys = true;
 }
}
"""
LEGACY_MAC = MAC.replace("flags = WMI_KEY", "flags |= WMI_KEY").replace("flags == WMI_KEY_PAIRWISE", "(flags & WMI_KEY_PAIRWISE)").replace("flags == WMI_KEY_GROUP", "(flags & WMI_KEY_GROUP)")
WMI = """int ath11k_wmi_vdev_install_key(void)
{
 if (arg->key_data)
  memcpy(tlv->value, (u8 *)arg->key_data, key_len_aligned);
}
"""


class Ath11kRekeyTests(unittest.TestCase):
    def prepare(self, root: Path, *, integrated: bool | str) -> tuple[Path, Path, Path]:
        tree = root / "linux"
        driver = tree / fix.DRIVER
        driver.mkdir(parents=True)
        for name, text in (("core.h", CORE if integrated else CORE_BEFORE),
                           ("mac.c", LEGACY_MAC if integrated == "legacy" else MAC if integrated else INSTALL), ("wmi.c", WMI)):
            (driver / name).write_text(text)
        subprocess.run(["git", "init", "--quiet", str(tree)], check=True)
        subprocess.run(["git", "-C", str(tree), "add", "."], check=True)
        subprocess.run(["git", "-C", str(tree), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", "fixture"], check=True)
        patch = root / "rekey.patch"
        lines = [f"From {fix.UPSTREAM_COMMIT} Mon Sep 17 00:00:00 2001\n"]
        for name, before, after in (("core.h", CORE_BEFORE, CORE), ("mac.c", INSTALL, LEGACY_MAC)):
            path = str(fix.DRIVER / name)
            lines.append(f"diff --git a/{path} b/{path}\n")
            lines.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"))
        patch.write_text("".join(lines))
        flags_patch = root / "flags.patch"
        path = str(fix.DRIVER / "mac.c")
        flags_patch.write_text(
            f"From {fix.FLAGS_COMMIT} Mon Sep 17 00:00:00 2001\n"
            f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
                LEGACY_MAC.splitlines(keepends=True), MAC.splitlines(keepends=True),
                fromfile=f"a/{path}", tofile=f"b/{path}",
            ))
        )
        return tree, patch, flags_patch

    def test_integrated_fix_preserves_all_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            tree, patch, flags_patch = self.prepare(Path(directory), integrated=True)
            before = fix.verify_integration(tree)
            report = fix.apply_fix(tree, patch, flags_patch)
            self.assertEqual(report["status"], "already-integrated")
            self.assertEqual(report["verified_files"], before)
            self.assertEqual(fix.verify_integration(tree), before)
            self.assertEqual(subprocess.check_output(["git", "-C", str(tree), "status", "--porcelain"]), b"")

    def test_missing_fix_is_applied_cleanly_and_verified(self):
        for integrated in (False, "legacy"):
            with self.subTest(integrated=integrated), tempfile.TemporaryDirectory() as directory:
                tree, patch, flags_patch = self.prepare(Path(directory), integrated=integrated)
                report = fix.apply_fix(tree, patch, flags_patch)
                self.assertEqual(report["status"], "applied")
                self.assertEqual((tree / fix.DRIVER / "mac.c").read_text(), MAC)
                self.assertEqual(report["supersedes"], fix.SUPERSEDED_COMMIT)
                self.assertEqual(report["upstream_commits"], [fix.UPSTREAM_COMMIT, fix.FLAGS_COMMIT])

    def test_failed_followup_rolls_back_the_first_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            tree, patch, flags_patch = self.prepare(Path(directory), integrated=False)
            flags_patch.write_text(flags_patch.read_text().replace("-  flags |= WMI_KEY_GROUP;", "-  flags |= UNEXPECTED;"))
            before = {path: path.read_bytes() for path in (tree / fix.DRIVER).iterdir()}
            with self.assertRaisesRegex(fix.RekeyError, "needs a reviewed port"):
                fix.apply_fix(tree, patch, flags_patch)
            self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))

    def test_initial_fix_with_broken_bitwise_flags_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            tree, _, _ = self.prepare(Path(directory), integrated="legacy")
            with self.assertRaisesRegex(fix.RekeyError, "key-type assignment correction is missing"):
                fix.verify_integration(tree)

    def test_obsolete_revert_is_rejected_even_when_modern_fix_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            tree, patch, flags_patch = self.prepare(Path(directory), integrated=True)
            patch.write_text(patch.read_text().replace(fix.UPSTREAM_COMMIT, fix.SUPERSEDED_COMMIT))
            before = fix.verify_integration(tree)
            with self.assertRaisesRegex(fix.RekeyError, "obsolete DISABLE_KEY revert is forbidden"):
                fix.apply_fix(tree, patch, flags_patch)
            self.assertEqual(fix.verify_integration(tree), before)

    def test_partial_integration_never_reports_success_or_changes_tree(self):
        for name, old, new in (
            ("mac.c", "arvif->num_stations++;", "ar->num_stations++;"),
            ("mac.c", "arg.key_cipher = WMI_CIPHER_NONE;", "arg.key_len = 0;"),
            ("mac.c", "cmd == SET_KEY || is_ap_with_no_sta", "cmd == SET_KEY"),
            ("wmi.c", "if (arg->key_data)", ""),
        ):
            with self.subTest(name=name, old=old), tempfile.TemporaryDirectory() as directory:
                tree, patch, flags_patch = self.prepare(Path(directory), integrated=True)
                source = tree / fix.DRIVER / name
                source.write_text(source.read_text().replace(old, new))
                before = {path: path.read_bytes() for path in (tree / fix.DRIVER).iterdir()}
                with self.assertRaisesRegex(fix.RekeyError, "needs a reviewed port"):
                    fix.apply_fix(tree, patch, flags_patch)
                self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))

    def test_manifest_fetches_the_upstream_successor_only(self):
        spec = json.loads((ROOT / "config/patch-sources.json").read_text())["components"]["ath11k_disable_key"]
        self.assertEqual(spec["urls"], [f"https://github.com/torvalds/linux/commit/{fix.UPSTREAM_COMMIT}.patch"])
        self.assertIn(fix.UPSTREAM_COMMIT, spec["required_markers"])
        followup = json.loads((ROOT / "config/patch-sources.json").read_text())["components"]["ath11k_rekey_flags"]
        self.assertEqual(followup["urls"], [f"https://github.com/torvalds/linux/commit/{fix.FLAGS_COMMIT}.patch"])


if __name__ == "__main__":
    unittest.main()
