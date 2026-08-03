#!/usr/bin/env python3
"""Guard the manual build/release contract without external YAML dependencies."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/validate-kernel.yml").read_text(
    encoding="utf-8"
)
DISPATCHER = (ROOT / ".github/workflows/release-on-main.yml").read_text(
    encoding="utf-8"
)
CONFIG = (ROOT / "config/kernelnote.config").read_text(encoding="utf-8")
BUILD_CORE = (ROOT / "scripts/build-kernelnote-core.sh").read_text(encoding="utf-8")
ZEN_REWRITER = (ROOT / "scripts/apply-zen-interactive.py").read_text(encoding="utf-8")
FINALIZER = (ROOT / "scripts/finalize-bore-stable-port.py").read_text(encoding="utf-8")


class ManualWorkflowContractTests(unittest.TestCase):
    def test_manual_runs_package_artifacts_and_gate_release_to_main(self) -> None:
        self.assertIn(
            "workflow_dispatch:\n"
            "    inputs:\n"
            "      publish_release:\n"
            "        description: Publish the compiled packages as a GitHub release (main only)\n"
            "        required: true\n"
            "        default: true\n"
            "        type: boolean",
            WORKFLOW,
        )
        self.assertNotIn("\n      mode:\n        description: Build mode", WORKFLOW)
        self.assertIn(
            "BUILD_MODE: ${{ github.event_name == 'pull_request' && startsWith(github.head_ref, 'validation/') && 'package' || github.event_name == 'pull_request' && 'validate' || 'package' }}",
            WORKFLOW,
        )

        package_artifact = WORKFLOW.split("      - name: Upload Debian packages", 1)[1].split(
            "      - name: Publish GitHub release", 1
        )[0]
        self.assertIn("logs/patch-lock.json", package_artifact)
        self.assertIn("retention-days: 14", package_artifact)

        release_step = WORKFLOW.split("      - name: Publish GitHub release", 1)[1].split(
            "      - name: Upload validation logs", 1
        )[0]
        self.assertIn("github.event_name == 'workflow_dispatch'", release_step)
        self.assertIn("github.ref_name == 'main'", release_step)
        self.assertIn("inputs.publish_release", release_step)
        self.assertIn("github.ref_name == 'integration/bore-7.1'", release_step)
        self.assertNotIn("env.BUILD_MODE == 'package'", release_step)

    def test_main_dispatcher_uses_the_current_manual_input_contract(self) -> None:
        self.assertIn("gh workflow run validate-kernel.yml", DISPATCHER)
        self.assertIn("--field publish_release=true", DISPATCHER)
        self.assertNotIn("--field mode=package", DISPATCHER)

    def test_python_validation_allows_an_empty_optional_glob(self) -> None:
        self.assertIn("shopt -s nullglob", WORKFLOW)
        self.assertIn(
            "python_sources=(scripts/apply-*.py scripts/resolve-*.py scripts/validate-*.py scripts/finalize-*.py)",
            WORKFLOW,
        )
        self.assertIn('python3 -m py_compile "${python_sources[@]}"', WORKFLOW)

    def test_zen_interactive_is_persistent_and_verified(self) -> None:
        self.assertIn("CONFIG_ZEN_INTERACTIVE=y", CONFIG)
        self.assertIn(
            "python3 scripts/apply-zen-interactive.py scripts/build-kernelnote-core.sh",
            WORKFLOW,
        )
        self.assertIn("grep -Fq 'CONFIG_ZEN_INTERACTIVE=y' logs/final.config", WORKFLOW)

    def test_reflex_keeps_vendor_pstate_drivers_in_passive_mode(self) -> None:
        self.assertIn("CONFIG_X86_INTEL_PSTATE=y", CONFIG)
        self.assertIn("CONFIG_X86_AMD_PSTATE=y", CONFIG)
        self.assertIn("CONFIG_X86_AMD_PSTATE_DEFAULT_MODE=2", CONFIG)
        self.assertIn("intel_pstate=passive", CONFIG)
        self.assertIn("amd_pstate=passive", CONFIG)
        for token in ("intel_pstate=passive", "amd_pstate=passive"):
            self.assertIn(token, BUILD_CORE)
            self.assertIn(f"grep -Fq '{token}' logs/final.config", WORKFLOW)
        self.assertIn('assert_cmdline_token "intel_pstate=passive"', BUILD_CORE)
        self.assertIn('assert_cmdline_token "amd_pstate=passive"', BUILD_CORE)
        self.assertIn("CONFIG_X86_AMD_PSTATE_DEFAULT_MODE=2", WORKFLOW)

    def test_zen_source_follows_the_resolved_kernel_series(self) -> None:
        self.assertIn('KERNEL_SERIES:-7.1', ZEN_REWRITER)
        self.assertIn("compatibility commits", ZEN_REWRITER)
        self.assertNotIn('ZEN_INTERACTIVE_REF="7.0/zen-sauce"', ZEN_REWRITER)

    def test_bore_port_is_finalized_after_dynamic_source_resolution(self) -> None:
        dynamic = (
            "python3 scripts/apply-zarpon-generic-name.py "
            "scripts/build-kernelnote-core.sh scripts/build-kernelnote.sh"
        )
        final = (
            "python3 scripts/finalize-bore-stable-port.py "
            "scripts/build-kernelnote-core.sh"
        )
        self.assertIn(final, WORKFLOW)
        self.assertLess(WORKFLOW.index(dynamic), WORKFLOW.index(final))

        self.assertIn("patch-lock.json", FINALIZER)
        self.assertIn('record.get("selection") != "exact"', FINALIZER)
        self.assertIn('record.get("kernel_target", "")', FINALIZER)
        self.assertIn('BORE_PATCH="$RESOLVED_PATCH_ROOT/{output}"', FINALIZER)
        self.assertIn('authenticated_patch(lock_path, record, "BORE")', FINALIZER)
        self.assertIn('authenticated_patch(lock_path, record, "BORE sched_ext")', FINALIZER)
        self.assertIn('f"locked {label} patch SHA-256 no longer matches the lock"', FINALIZER)
        self.assertNotIn("materialize_bore_port", FINALIZER)
        self.assertNotIn("6.8.0-rc1", FINALIZER)


if __name__ == "__main__":
    unittest.main()
