#!/usr/bin/env python3
"""Check the kernel.org mainline/stable repository policy in generated builds."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpstreamKernelRepositoryTests(unittest.TestCase):
    def test_generated_build_selects_correct_kernel_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / "build-kernelnote-core.sh"
            generated.write_text(
                (ROOT / "scripts/build-kernelnote-core.sh").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/apply-upstream-generic.py"), str(generated)],
                check=True,
                cwd=ROOT,
            )
            text = generated.read_text(encoding="utf-8")
            self.assertIn("Cloned kernel version mismatch:", text)
            self.assertIn('actual_kernel_version="$(make -s -C "$KERNELDIR" kernelversion)"', text)
            policy = 'KERNEL_REPO=' + text.split('KERNEL_REPO=', 1)[1].split('\nADIOS_URL=', 1)[0]
            subprocess.run(["bash", "-n"], input=policy, text=True, check=True)
            for version, owner in (
                ("7.3", "torvalds"),
                ("7.4-rc1", "torvalds"),
                ("7.4-rc12", "torvalds"),
                ("7.3.1", "stable"),
                ("7.3.10", "stable"),
            ):
                with self.subTest(version=version):
                    result = subprocess.run(
                        ["bash", "-c", 'set -euo pipefail\n' + policy + '\nprintf "%s" "$KERNEL_REPO"'],
                        env={**os.environ, "KERNEL_VERSION": version},
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        result.stdout,
                        f"https://git.kernel.org/pub/scm/linux/kernel/git/{owner}/linux.git",
                    )


if __name__ == "__main__":
    unittest.main()
