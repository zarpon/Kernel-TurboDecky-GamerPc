#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/port-cpu-optimizations-7.2.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cpu_opt_72_port", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


port = load_module()


USERCOPY_OLD = (
    "\tdepends on MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || "
    "M586MMX || X86_GENERIC || MK7 || MEFFICEON"
)
CHECKSUM_OLD = (
    "\tdepends on MWINCHIP3D || MWINCHIPC6 || MCYRIXIII || MK7 || MK6 || "
    "MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M686 || "
    "MVIAC3_2 || MVIAC7 || MEFFICEON || MGEODE_LX || MATOM"
)
PAE_OLD = (
    "\tdepends on MCRUSOE || MEFFICEON || MCYRIXIII || MPENTIUM4 || MPENTIUMM || "
    "MPENTIUMIII || MPENTIUMII || M686 || MVIAC7 || MATOM || X86_64"
)
TSC_OLD = (
    "\tdepends on (MWINCHIP3D || MCRUSOE || MEFFICEON || MCYRIXIII || MK7 || MK6 || "
    "MPENTIUM4 || MPENTIUMM || MPENTIUMIII || MPENTIUMII || M686 || M586MMX || "
    "M586TSC || MVIAC3_2 || MVIAC7 || MGEODEGX1 || MGEODE_LX || MATOM) || X86_64"
)


def fixture() -> str:
    return f"""config GENERIC_CPU
\tbool \"Generic\"
config MZEN5
\tbool \"Zen 5\"
config MDIAMONDRAPIDS
\tbool \"Diamond Rapids\"
config X86_64_VERSION
\tint \"ISA\"

config X86_INTEL_USERCOPY
\tdef_bool y
{USERCOPY_OLD}

config X86_USE_PPRO_CHECKSUM
\tdef_bool y
{CHECKSUM_OLD}

config X86_TSC
\tdef_bool y

config X86_HAVE_PAE
\tdef_bool y
{PAE_OLD}
"""


def reject_fixture() -> str:
    return f"""--- arch/x86/Kconfig.cpu
+++ arch/x86/Kconfig.cpu
@@ -309,19 +720,19 @@ config X86_ALIGNMENT_16
 config X86_INTEL_USERCOPY
-{USERCOPY_OLD}
+\tdepends on expanded-usercopy
 config X86_USE_PPRO_CHECKSUM
-{CHECKSUM_OLD}
+\tdepends on expanded-checksum
 config X86_TSC
-{TSC_OLD}
+\tdepends on expanded-tsc
 config X86_HAVE_PAE
-{PAE_OLD}
+\tdepends on expanded-pae
"""


class CpuOptimization72PortTests(unittest.TestCase):
    def test_known_linux_72_reject_is_ported_without_restoring_tsc_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kconfig = root / "Kconfig.cpu"
            reject = root / "Kconfig.cpu.rej"
            kconfig.write_text(fixture(), encoding="utf-8")
            reject.write_text(reject_fixture(), encoding="utf-8")

            port.port_kconfig(kconfig, reject, "7.2")
            result = kconfig.read_text(encoding="utf-8")

            self.assertIn("MK8 || MK7 || MEFFICEON || MCORE2", result)
            self.assertIn("MCORE2 || MATOM || MK8SSE3", result)
            self.assertIn("M686 || MK8 || MVIAC7 || MCORE2", result)
            self.assertIn("config X86_TSC\n\tdef_bool y\n\nconfig X86_HAVE_PAE", result)
            self.assertNotIn(TSC_OLD, result)

    def test_unrelated_reject_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kconfig = root / "Kconfig.cpu"
            reject = root / "Kconfig.cpu.rej"
            kconfig.write_text(fixture(), encoding="utf-8")
            reject.write_text("@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")
            with self.assertRaises(port.PortError):
                port.port_kconfig(kconfig, reject, "7.2")

    def test_other_kernel_series_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kconfig = root / "Kconfig.cpu"
            reject = root / "Kconfig.cpu.rej"
            kconfig.write_text(fixture(), encoding="utf-8")
            reject.write_text(reject_fixture(), encoding="utf-8")
            with self.assertRaises(port.PortError):
                port.port_kconfig(kconfig, reject, "7.3")


if __name__ == "__main__":
    unittest.main()
