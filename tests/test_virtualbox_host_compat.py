#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/apply-latest-stable-series.py"
SPEC = importlib.util.spec_from_file_location("apply_latest_stable_series", MODULE_PATH)
assert SPEC and SPEC.loader
rewriter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rewriter)


class VirtualBoxHostCompatibilityTest(unittest.TestCase):
    def test_wrapper_enforces_virtualbox_host_requirements(self) -> None:
        fixture = '''  "cpuidle.governor=nap"
)
scripts/config --enable CPU_IDLE_GOV_NAP
assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"
assert_cmdline_token "cpuidle.governor=nap"
'''
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / "build-kernelnote.sh"
            wrapper.write_text(fixture, encoding="utf-8")
            rewriter.patch_wrapper(wrapper)
            output = wrapper.read_text(encoding="utf-8")

        required = (
            '"kvm.enable_virt_at_load=0"',
            "scripts/config --enable MODULES",
            "scripts/config --enable MODULE_UNLOAD",
            "scripts/config --enable MODULE_FORCE_UNLOAD",
            "scripts/config --enable KALLSYMS",
            "scripts/config --enable KALLSYMS_ALL",
            "scripts/config --enable VIRTUALIZATION",
            "scripts/config --module KVM",
            "scripts/config --module KVM_INTEL",
            "scripts/config --module KVM_AMD",
            "scripts/config --module TUN",
            "scripts/config --module BRIDGE",
            "scripts/config --enable NETFILTER",
            'assert_config "CONFIG_KVM_INTEL=m"',
            'assert_config "CONFIG_KVM_AMD=m"',
            'assert_cmdline_token "kvm.enable_virt_at_load=0"',
        )
        for value in required:
            self.assertIn(value, output)

    def test_static_config_contains_virtualbox_requirements(self) -> None:
        config = (ROOT / "config/kernelnote.config").read_text(encoding="utf-8")
        for value in (
            "CONFIG_MODULES=y",
            "CONFIG_MODULE_UNLOAD=y",
            "CONFIG_KALLSYMS=y",
            "CONFIG_KVM=m",
            "CONFIG_KVM_INTEL=m",
            "CONFIG_KVM_AMD=m",
            "CONFIG_TUN=m",
            "CONFIG_BRIDGE=m",
            "CONFIG_NETFILTER=y",
            "kvm.enable_virt_at_load=0",
        ):
            self.assertIn(value, config)


if __name__ == "__main__":
    unittest.main()
