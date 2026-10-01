import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/apply-zarpon-generic-name.py"
SPEC = importlib.util.spec_from_file_location("zarpon_generic_name", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class KernelReleaseRewriterTests(unittest.TestCase):
    def test_adds_dynamic_kernelrelease_to_plain_make(self) -> None:
        source = "MAKE=(make LLVM=1 LLVM_IAS=1)\n"

        rewritten = MODULE.ensure_kernelrelease_makevar(source)

        self.assertEqual(rewritten.count('KERNELRELEASE="$KERNEL_RELEASE_NAME"'), 1)
        self.assertIn('${KERNEL_RELEASE_NAME:?latest stable kernel identity was not resolved}', rewritten)

    def test_preserves_dynamic_kernelrelease_inserted_by_earlier_rewriter(self) -> None:
        source = (
            ': "${KERNEL_RELEASE_NAME:?latest stable kernel identity was not resolved}"\n'
            'MAKE=(make LLVM=1 LLVM_IAS=1 KERNELRELEASE="$KERNEL_RELEASE_NAME")\n'
        )

        self.assertEqual(MODULE.ensure_kernelrelease_makevar(source), source)

    def test_rejects_missing_or_ambiguous_make_anchor(self) -> None:
        with self.assertRaises(SystemExit):
            MODULE.ensure_kernelrelease_makevar("MAKE=(make)\n")


if __name__ == "__main__":
    unittest.main()
