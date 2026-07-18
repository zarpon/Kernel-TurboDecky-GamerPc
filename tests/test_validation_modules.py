#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REWRITER = ROOT / "scripts/apply-validation-modules.py"


class ValidationModuleRewriteTests(unittest.TestCase):
    def test_injects_full_module_build_and_key_product_checks(self) -> None:
        fixture = '''if [[ "$MODE" == "package" ]]; then
  echo package
else
  echo "==> Validating built-in kernel and Clang ThinLTO link with $JOBS parallel jobs"
  "${MAKE[@]}" -j"$JOBS" bzImage
  test -s arch/x86/boot/bzImage
  test -s vmlinux
  file arch/x86/boot/bzImage vmlinux | tee "$LOGDIR/build-products.txt"
fi
'''
        with tempfile.TemporaryDirectory() as directory:
            core = Path(directory) / "core.sh"
            core.write_text(fixture, encoding="utf-8")
            subprocess.run([sys.executable, str(REWRITER), str(core)], check=True)
            subprocess.run(["bash", "-n", str(core)], check=True)
            text = core.read_text(encoding="utf-8")
            self.assertIn('"${MAKE[@]}" -j"$JOBS" modules', text)
            self.assertIn("drivers/block/zram/zram.ko", text)
            self.assertIn("drivers/gpu/drm/ttm/ttm.ko", text)
            self.assertIn("drivers/gpu/drm/amd/amdgpu/amdgpu.ko", text)
            self.assertIn("net/mac80211/mac80211.ko", text)
            self.assertIn("ath11k_ahb.ko", text)
            self.assertIn("ath11k_pci.ko", text)
            self.assertIn("Patch reject/original files remain", text)

    def test_requires_the_exact_validation_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            core = Path(directory) / "core.sh"
            core.write_text("echo unrelated\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(REWRITER), str(core)],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected exactly one anchor", result.stderr)


if __name__ == "__main__":
    unittest.main()
