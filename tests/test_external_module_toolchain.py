#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/patch-external-module-toolchain.py"
SPEC = importlib.util.spec_from_file_location("patch_external_module_toolchain", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


FIXTURE = """KBUILD_EXTMOD := $(M)
export KBUILD_EXTMOD

# An unrelated LLVM conditional exists earlier in the real Linux Makefile.
ifneq ($(LLVM),)
LLVM_TOOLS := enabled
endif

# Compiler-selection block that must receive the TurboDecky default.
ifneq ($(LLVM),)
ifneq ($(filter %/,$(LLVM)),)
LLVM_PREFIX := $(LLVM)
else ifneq ($(filter -%,$(LLVM)),)
LLVM_SUFFIX := $(LLVM)
endif
endif

ifdef CONFIG_POLLY_CLANG
KBUILD_CFLAGS += -mllvm -polly \
                 -mllvm -polly-loopfusion-greedy
ifdef CONFIG_LD_DEAD_CODE_DATA_ELIMINATION
KBUILD_CFLAGS += -mllvm -polly-run-dce
endif
endif

# Tell gcc to never replace conditional load with a non-conditional one
ifdef CONFIG_CC_IS_GCC
endif
"""


class ExternalModuleToolchainTest(unittest.TestCase):
    def test_external_modules_default_to_llvm_and_skip_polly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            makefile = Path(directory) / "Makefile"
            makefile.write_text(FIXTURE, encoding="utf-8")
            module.patch_makefile(makefile)
            first = makefile.read_text(encoding="utf-8")
            module.patch_makefile(makefile)
            second = makefile.read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertIn(module.MARKER, first)
        self.assertEqual(first.count(module.MARKER), 1)
        self.assertIn('ifeq ("$(origin LLVM)", "undefined")', first)
        self.assertIn("ifneq ($(KBUILD_EXTMOD),)\nLLVM := 1", first)
        self.assertIn(
            module.MARKER + "\nifeq",
            first,
        )
        self.assertIn(
            "endif\n\nifneq ($(LLVM),)\nifneq ($(filter %/,$(LLVM)),)",
            first,
        )
        self.assertIn(
            "ifdef CONFIG_POLLY_CLANG\nifeq ($(KBUILD_EXTMOD),)\nKBUILD_CFLAGS",
            first,
        )
        self.assertIn(
            "KBUILD_CFLAGS += -mllvm -polly-run-dce\nendif\nendif\nendif\n\n# Tell gcc",
            first,
        )

    def test_pipeline_runs_patch_after_polly_integration(self) -> None:
        integrator = (
            ROOT / "scripts/apply-latest-stable-series.py"
        ).read_text(encoding="utf-8")
        polly_completion = (
            'git diff --check -- Makefile init/Kconfig | tee '
            '"$LOGDIR/polly-toolchain-diff-check.log"'
        )
        helper = 'python3 "$ROOT/scripts/patch-external-module-toolchain.py" Makefile'

        self.assertEqual(integrator.count(helper), 1)
        self.assertLess(integrator.index(polly_completion), integrator.index(helper))
        self.assertNotIn(
            'python3 "$ROOT/scripts/patch-external-module-toolchain.py" Makefile\n\n'
            'cp "$WORKDIR/liquorix-amd64.config" .config',
            integrator,
        )


if __name__ == "__main__":
    unittest.main()
