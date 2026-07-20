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
    def test_kernel_identity_is_debian_compatible_and_has_no_release_suffix(self) -> None:
        payload = json.dumps(
            {
                "latest_stable": {"version": "7.1.4"},
                "releases": [
                    {
                        "moniker": "stable",
                        "version": "7.1.4",
                        "iseol": False,
                        "source": "https://example.invalid/linux-7.1.4.tar.xz",
                        "gitweb": "https://example.invalid/v7.1.4",
                        "released": {"isodate": "2026-07-19"},
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

        self.assertEqual(env["KERNEL_RELEASE_NAME"], "7.1.4.turbodecky")
        self.assertEqual(env["KERNEL_PUBLISH_NAME"], "linux.7.1.4.turbodecky")
        self.assertEqual(env["KERNEL_ARTIFACT_NAME"], "linux.7.1.4.turbodecky-debs")
        self.assertEqual(outputs["kernel_release"], "7.1.4.turbodecky")
        self.assertNotIn(".release", "\n".join([*env.values(), *outputs.values()]))
        subprocess.run(
            ["dpkg", "--validate-version", env["KERNEL_RELEASE_NAME"]],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
