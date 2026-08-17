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
SPEC = importlib.util.spec_from_file_location("resolve_latest_stable", MODULE_PATH)
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


class LatestStableIdentityTest(unittest.TestCase):
    def run_resolver(
        self, version: str, moniker: str
    ) -> tuple[dict[str, str], dict[str, str]]:
        payload = json.dumps(
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
        ).encode()

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
                return_value=FakeResponse(payload),
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
        return env, outputs

    def assert_identity(self, version: str, moniker: str) -> None:
        env, outputs = self.run_resolver(version, moniker)
        expected_release = f"{version}.turbodecky"
        expected_publish = f"linux.{expected_release}"
        self.assertEqual(env["KERNEL_VERSION"], version)
        self.assertEqual(env["KERNEL_SERIES"], ".".join(version.split(".")[:2]))
        self.assertEqual(env["KERNEL_RELEASE_NAME"], expected_release)
        self.assertEqual(env["KERNEL_PUBLISH_NAME"], expected_publish)
        self.assertEqual(env["KERNEL_ARTIFACT_NAME"], f"{expected_publish}-debs")
        self.assertEqual(outputs["kernel_release"], expected_release)
        self.assertNotIn(".release", "\n".join([*env.values(), *outputs.values()]))
        subprocess.run(
            ["dpkg", "--validate-version", env["KERNEL_RELEASE_NAME"]],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_patchlevel_stable_release(self) -> None:
        self.assert_identity("7.1.8", "stable")

    def test_new_two_component_mainline_release_is_latest_stable(self) -> None:
        self.assert_identity("7.2", "mainline")

    def test_future_two_component_release(self) -> None:
        self.assert_identity("8.0", "mainline")

    def test_future_patchlevel_release(self) -> None:
        self.assert_identity("8.0.1", "stable")

    def test_stable_record_wins_during_transition(self) -> None:
        payload = {
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
        selected = resolver.select_release(payload, "8.1")
        self.assertEqual(selected["moniker"], "stable")


if __name__ == "__main__":
    unittest.main()
