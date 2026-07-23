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
            "BUILD_MODE: ${{ github.event_name == 'pull_request' && 'validate' || 'package' }}",
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


if __name__ == "__main__":
    unittest.main()
