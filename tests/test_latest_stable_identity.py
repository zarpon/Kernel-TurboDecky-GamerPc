#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/resolve-latest-stable.py"
SPEC = importlib.util.spec_from_file_location("resolve_latest_upstream", MODULE_PATH)
assert SPEC and SPEC.loader
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class LatestUpstreamIdentityTest(unittest.TestCase):
    def run_payload(
        self, payload: dict
    ) -> tuple[dict[str, str], dict[str, str]]:
        raw = json.dumps(payload).encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / "github-env"
            output_file = root / "github-output"
            log_dir = root / "logs"
            argv = [
                str(MODULE_PATH),
                "--github-env",
                str(env_file),
                "--github-output",
                str(output_file),
                "--log-dir",
                str(log_dir),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                resolver.urllib.request,
                "urlopen",
                return_value=FakeResponse(raw),
            ), mock.patch("sys.stdout", new=io.StringIO()):
                resolver.main()

            env = dict(
                line.split("=", 1)
                for line in env_file.read_text(encoding="utf-8").splitlines()
            )
            outputs = dict(
                line.split("=", 1)
                for line in output_file.read_text(encoding="utf-8").splitlines()
            )
            self.assertTrue((log_dir / "latest-upstream-kernel.txt").is_file())
        return env, outputs

    def run_resolver(
        self, version: str, moniker: str
    ) -> tuple[dict[str, str], dict[str, str]]:
        return self.run_payload(
            {
                "latest_stable": {"version": version},
                "releases": [
                    {
                        "moniker": moniker,
                        "version": version,
                        "iseol": False,
                        "source": f"https://example.invalid/linux-{version}.tar.xz",
                        "gitweb": f"https://example.invalid/v{version}",
                        "released": {"isodate": "2026-08-16"},
                    }
                ],
            }
        )

    def assert_identity(self, version: str, moniker: str) -> None:
        env, outputs = self.run_resolver(version, moniker)
        expected_release = f"{version}.turbodecky"
        expected_publish = f"linux.{expected_release}"
        expected_series = ".".join(version.split("-")[0].split(".")[:2])
        self.assertEqual(env["KERNEL_VERSION"], version)
        self.assertEqual(env["KERNEL_SERIES"], expected_series)
        self.assertEqual(env["KERNEL_TAG"], f"v{version}")
        self.assertEqual(env["KERNEL_RELEASE_NAME"], expected_release)
        self.assertEqual(env["KERNEL_PUBLISH_NAME"], expected_publish)
        self.assertEqual(env["KERNEL_ARTIFACT_NAME"], f"{expected_publish}-debs")
        self.assertEqual(outputs["kernel_release"], expected_release)
        self.assertEqual(outputs["series"], expected_series)
        self.assertNotIn(".release", "\n".join([*env.values(), *outputs.values()]))
        subprocess.run(
            ["dpkg", "--validate-version", env["KERNEL_RELEASE_NAME"]],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_patchlevel_stable_release(self) -> None:
        self.assert_identity("7.2.6", "stable")

    def test_two_component_final_mainline_release(self) -> None:
        self.assert_identity("7.3", "mainline")

    def test_release_candidate_identity(self) -> None:
        self.assert_identity("7.3-rc3", "mainline")

    def test_future_patchlevel_release(self) -> None:
        self.assert_identity("8.0.1", "stable")

    def test_newer_release_candidate_beats_older_stable_series(self) -> None:
        payload = {
            "latest_stable": {"version": "7.2.6"},
            "releases": [
                {
                    "moniker": "stable",
                    "version": "7.2.6",
                    "iseol": False,
                    "source": "https://example.invalid/linux-7.2.6.tar.xz",
                },
                {
                    "moniker": "mainline",
                    "version": "7.3-rc3",
                    "iseol": False,
                    "source": "https://example.invalid/linux-7.3-rc3.tar.xz",
                },
            ],
        }
        env, _ = self.run_payload(payload)
        self.assertEqual(env["KERNEL_VERSION"], "7.3-rc3")
        self.assertEqual(env["KERNEL_SERIES"], "7.3")

    def test_newer_rc_number_wins_within_same_series(self) -> None:
        selected = resolver.select_latest_release(
            {
                "releases": [
                    {
                        "moniker": "mainline",
                        "version": "7.3-rc2",
                        "iseol": False,
                        "source": "https://example.invalid/rc2.tar.xz",
                    },
                    {
                        "moniker": "mainline",
                        "version": "7.3-rc3",
                        "iseol": False,
                        "source": "https://example.invalid/rc3.tar.xz",
                    },
                ]
            }
        )
        self.assertEqual(selected["version"], "7.3-rc3")

    def test_final_release_beats_rc_of_same_series(self) -> None:
        selected = resolver.select_latest_release(
            {
                "releases": [
                    {
                        "moniker": "mainline",
                        "version": "8.1-rc7",
                        "iseol": False,
                        "source": "https://example.invalid/rc.tar.xz",
                    },
                    {
                        "moniker": "mainline",
                        "version": "8.1",
                        "iseol": False,
                        "source": "https://example.invalid/final.tar.xz",
                    },
                ]
            }
        )
        self.assertEqual(selected["version"], "8.1")

    def test_stable_record_wins_equal_version_transition(self) -> None:
        selected = resolver.select_latest_release(
            {
                "releases": [
                    {
                        "moniker": "mainline",
                        "version": "8.1",
                        "iseol": False,
                        "source": "https://example.invalid/mainline.tar.xz",
                    },
                    {
                        "moniker": "stable",
                        "version": "8.1",
                        "iseol": False,
                        "source": "https://example.invalid/stable.tar.xz",
                    },
                ]
            }
        )
        self.assertEqual(selected["moniker"], "stable")


if __name__ == "__main__":
    unittest.main()
