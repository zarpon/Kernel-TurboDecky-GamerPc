from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("requested_patches", ROOT / "scripts/apply-requested-patch-series.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class FirmwareInfoTests(unittest.TestCase):
    def test_missing_flag_definition_is_added_once_with_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            loader = tree / "drivers/base/firmware_loader"
            loader.mkdir(parents=True)
            (loader / "main.c").write_text('#ifdef CONFIG_GENTOO_PRINT_FIRMWARE_INFO\nprintk("Loading firmware: %s", name);\n#endif\n')
            kconfig = loader / "Kconfig"
            kconfig.write_text('config FW_LOADER\n\ttristate "Firmware loader"\n')
            module.configure_firmware_info(tree)
            first = kconfig.read_text()
            self.assertIn('config GENTOO_PRINT_FIRMWARE_INFO\n\tbool', first)
            self.assertIn('\tdepends on FW_LOADER\n', first)
            module.configure_firmware_info(tree)
            self.assertEqual(kconfig.read_text(), first)

    def test_unpatched_source_is_rejected_without_editing_kconfig(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            loader = tree / "drivers/base/firmware_loader"
            loader.mkdir(parents=True)
            (loader / "main.c").write_text('printk("Loading firmware: %s", name);\n')
            kconfig = loader / "Kconfig"
            kconfig.write_text('config FW_LOADER\n\ttristate "Firmware loader"\n')
            before = kconfig.read_bytes()
            with self.assertRaisesRegex(SystemExit, "maintained firmware-info patch is not present"):
                module.configure_firmware_info(tree)
            self.assertEqual(kconfig.read_bytes(), before)

    def test_generated_build_enables_and_asserts_firmware_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            core = Path(directory) / "core.sh"
            wrapper = Path(directory) / "build-kernelnote.sh"
            core.write_bytes((ROOT / "scripts/build-kernelnote-core.sh").read_bytes())
            wrapper.write_bytes((ROOT / "scripts/build-kernelnote.sh").read_bytes())
            subprocess.run(["python3", str(ROOT / "scripts/apply-reflex-core.py"), str(core), str(wrapper)], check=True)
            subprocess.run(["python3", str(ROOT / "scripts/apply-upstream-generic.py"), str(core)], check=True)
            subprocess.run(["python3", str(ROOT / "scripts/apply-requested-patch-series.py"), str(core)], check=True)
            text = core.read_text()
            self.assertIn('--configure-firmware-info "$KERNELDIR"', text)
            self.assertIn('scripts/config --enable GENTOO_PRINT_FIRMWARE_INFO', text)
            self.assertIn('assert_config "CONFIG_GENTOO_PRINT_FIRMWARE_INFO=y"', text)
            self.assertIn('scripts/apply-ath11k-rekey-fix.py', text)
            self.assertNotIn('apply_requested_patch "ath11k DISABLE_KEY revert"', text)
            subprocess.run(["bash", "-n", str(core)], check=True)

    def test_source_uses_maintained_kernel_series(self):
        spec = json.loads((ROOT / "config/patch-sources.json").read_text())["components"]["firmware_name"]
        self.assertEqual(spec["urls"], ["https://dev.gentoo.org/~mpagano/genpatches/trunk/{series}/3000_Support-printing-firmware-info.patch"])
        self.assertIn("CONFIG_GENTOO_PRINT_FIRMWARE_INFO", spec["required_markers"])


if __name__ == "__main__":
    unittest.main()
