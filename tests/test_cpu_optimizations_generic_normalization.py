#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/normalize-cpu-optimizations-generic.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cpu_opt_generic", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


normalizer = load_module()


def kconfig_fixture(with_gate: bool = True) -> str:
    gate = "\tdepends on !X86_NATIVE_CPU\n" if with_gate else ""
    return (
        "config X86_NATIVE_CPU\n"
        "\tbool \"Build and optimize for local/native CPU\"\n"
        "\tdepends on X86_64\n\n"
        "choice\n"
        "\tprompt \"x86_64 Compiler Build Optimization\"\n"
        f"{gate}"
        "\tdefault GENERIC_CPU\n\n"
        "config GENERIC_CPU\n"
        "\tbool \"Generic-x86-64\"\n\n"
        "config X86_64_VERSION\n"
        "\tint \"x86-64 compiler ISA level\"\n\n"
        "endchoice\n"
    )


GUARDED_MAKEFILE = """ifdef CONFIG_X86_NATIVE_CPU
        KBUILD_CFLAGS += -march=native
        KBUILD_RUSTFLAGS += -Ctarget-cpu=native
else
ifdef CONFIG_GENERIC_CPU
        KBUILD_CFLAGS += -mtune=generic
endif
endif
"""


class GenericCpuOptimizationNormalizationTests(unittest.TestCase):
    def test_native_gate_is_removed_but_upstream_native_symbol_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kconfig = root / "Kconfig.cpu"
            makefile = root / "Makefile"
            kconfig.write_text(kconfig_fixture(), encoding="utf-8")
            makefile.write_text(GUARDED_MAKEFILE, encoding="utf-8")

            changed = normalizer.normalize(kconfig, makefile)
            result = kconfig.read_text(encoding="utf-8")

            self.assertTrue(changed)
            self.assertNotIn("depends on !X86_NATIVE_CPU", result)
            self.assertIn("config X86_NATIVE_CPU", result)
            self.assertIn("config GENERIC_CPU", result)

    def test_normalization_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kconfig = root / "Kconfig.cpu"
            makefile = root / "Makefile"
            kconfig.write_text(kconfig_fixture(with_gate=False), encoding="utf-8")
            makefile.write_text(GUARDED_MAKEFILE, encoding="utf-8")

            self.assertFalse(normalizer.normalize(kconfig, makefile))

    def test_unguarded_march_native_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kconfig = root / "Kconfig.cpu"
            makefile = root / "Makefile"
            kconfig.write_text(kconfig_fixture(), encoding="utf-8")
            makefile.write_text("KBUILD_CFLAGS += -march=native\n", encoding="utf-8")

            with self.assertRaises(normalizer.NormalizeError):
                normalizer.normalize(kconfig, makefile)


if __name__ == "__main__":
    unittest.main()
