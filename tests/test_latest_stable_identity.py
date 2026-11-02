#!/usr/bin/env python3
"""Regression coverage for stable-only Linux source identity selection."""
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
    def __init__(self, payload: bytes):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self):
        return self.payload


def release(version: str, moniker: str = "stable", *, eol: bool = False,
            source: bool = True) -> dict:
    return {"version": version, "moniker": moniker, "iseol": eol,
            "source": f"https://example.invalid/linux-{version}.tar.xz" if source else "",
            "gitweb": f"https://example.invalid/v{version}",
            "released": {"isodate": "2026-10-31"}}


class LatestStableIdentityTest(unittest.TestCase):
    def run_payload(self, payload: dict) -> tuple[dict[str, str], dict[str, str]]:
        raw = json.dumps(payload).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file, output_file, log_dir = root / "env", root / "output", root / "logs"
            argv = [str(MODULE_PATH), "--github-env", str(env_file),
                    "--github-output", str(output_file), "--log-dir", str(log_dir)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                resolver.urllib.request, "urlopen", return_value=FakeResponse(raw)
            ) as urlopen, mock.patch("sys.stdout", new=io.StringIO()):
                resolver.main()
                urlopen.assert_called_once()
            env = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
            outputs = dict(line.split("=", 1) for line in output_file.read_text().splitlines())
            self.assertTrue((log_dir / "latest-upstream-kernel.txt").is_file())
            policy = json.loads((log_dir / "torvalds-linux-tag-reconciliation.json").read_text())
            self.assertEqual(policy["policy"], "stable-only")
            self.assertEqual(policy["refs"], [])
            self.assertEqual(policy["selected"], env["KERNEL_VERSION"])
        return env, outputs

    def assert_identity(self, version: str) -> None:
        env, outputs = self.run_payload({"releases": [release(version)]})
        kernel_release = f"{version}.turbodecky"
        publish_name = f"linux.{kernel_release}"
        self.assertEqual(env["KERNEL_VERSION"], version)
        self.assertEqual(env["KERNEL_SERIES"], ".".join(version.split(".")[:2]))
        self.assertEqual(env["KERNEL_TAG"], f"v{version}")
        self.assertEqual(env["KERNEL_RELEASE_NAME"], kernel_release)
        self.assertEqual(env["KERNEL_PUBLISH_NAME"], publish_name)
        self.assertEqual(env["KERNEL_ARTIFACT_NAME"], f"{publish_name}-debs")
        self.assertEqual(outputs["kernel_release"], kernel_release)
        self.assertEqual(outputs["series"], env["KERNEL_SERIES"])
        self.assertEqual(env["KERNEL_UPSTREAM_COMMIT"], "")
        self.assertEqual(env["KERNEL_UPSTREAM_TAG_SHA"], "")
        self.assertNotIn(".release", "\n".join([*env.values(), *outputs.values()]))
        subprocess.run(["dpkg", "--validate-version", kernel_release],
                       check=True, capture_output=True, text=True)

    def test_patchlevel_stable(self):
        self.assert_identity("7.2.6")
    def test_two_component_final_stable(self):
        self.assert_identity("7.3")
    def test_future_patchlevel_stable(self):
        self.assert_identity("8.0.1")

    def test_rc_never_overrides_stable(self):
        env, _ = self.run_payload({"releases": [release("7.3.1"),
                                     release("7.4-rc1", "mainline")]})
        self.assertEqual(env["KERNEL_VERSION"], "7.3.1")
    def test_mainline_final_never_overrides_stable_channel(self):
        env, _ = self.run_payload({"releases": [release("7.2.7"),
                                     release("7.3", "mainline")]})
        self.assertEqual(env["KERNEL_VERSION"], "7.2.7")
    def test_rc_only_fails_closed(self):
        with self.assertRaisesRegex(SystemExit, "stable final release"):
            resolver.select_latest_release({"releases": [release("7.4-rc1", "mainline")]})
    def test_rc_mislabeled_as_stable_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "stable final release"):
            resolver.select_latest_release({"releases": [release("7.3.1-rc2", "stable")]})
    def test_no_source_or_eol_fails_closed(self):
        with self.assertRaisesRegex(SystemExit, "stable final release"):
            resolver.select_latest_release({"releases": [release("7.3.1", source=False),
                                                        release("7.3.2", eol=True)]})
    def test_stable_patchlevel_and_series_ordering(self):
        chosen = resolver.select_latest_release({"releases": [
            release(v) for v in ["7.2.19", "7.3.1", "7.2.21", "7.3.3", "7.3.2"]]})
        self.assertEqual(chosen["version"], "7.3.3")
    def test_stable_record_wins_equal_version_transition(self):
        chosen = resolver.select_latest_release({"releases": [
            release("7.3", "mainline"), release("7.3", "stable")]})
        self.assertEqual(chosen["moniker"], "stable")
    def test_mixed_invalid_release_records(self):
        chosen = resolver.select_latest_release({"releases": [
            release("7.3.1"), release("7.4-rc3", "mainline"),
            release("8.0", "mainline"), release("8.1.2", "stable", eol=True),
            release("8.2.1", "stable", source=False)]})
        self.assertEqual(chosen["version"], "7.3.1")


if __name__ == "__main__":
    unittest.main()
