#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "tests/test_dynamic_patch_resolver.py"
text = path.read_text(encoding="utf-8")
if "import hashlib\n" not in text:
    if text.count("import json\n") != 1:
        raise SystemExit("json import did not match exactly once")
    text = text.replace("import json\n", "import hashlib\nimport json\n", 1)
old = '''    def test_approved_sha_prevents_a_stale_local_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            init_repo(
                repo,
                {
                    "patches/testing/0001-linux7.1-rc1-bore-6.8.0-rc1.patch": patch(
                        "bore 6.8.0-rc1", "kernel/sched/bore"
                    )
                },
            )
            manifest = {
                "schema": 1,
                "components": {
                    "bore": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/testing/*linux{series}*bore*.patch"],
                        "fallback_globs": [],
                        "require_exact_series": True,
                        "output": "bore.patch",
                        "approved_sha256": "0" * 64,
                        "required_markers": ["kernel/sched/bore"],
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3", str(RESOLVER), "--manifest", str(manifest_path),
                    "--output-dir", str(tmp / "resolved"), "--kernel-version", "7.1.4",
                    "--kernel-series", "7.1",
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewed local port requires", result.stderr)

'''
new = '''    def test_dynamic_upstream_sha_is_recorded_in_the_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            source = patch("bore 6.8.0", "kernel/sched/bore")
            selected_path = "patches/testing/0001-linux7.1.5-bore-6.8.0.patch"
            init_repo(repo, {selected_path: source})
            manifest = {
                "schema": 1,
                "components": {
                    "bore": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/testing/*linux{series}*bore*.patch"],
                        "fallback_globs": [],
                        "require_exact_series": True,
                        "output": "bore.patch",
                        "project_version_regex": r"bore[-_]?([0-9]+(?:\.[0-9]+)+(?:-rc[0-9]+)?)",
                        "required_markers": ["kernel/sched/bore"],
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output_dir = tmp / "resolved"
            result = subprocess.run(
                [
                    "python3", str(RESOLVER), "--manifest", str(manifest_path),
                    "--output-dir", str(output_dir), "--kernel-version", "7.1.5",
                    "--kernel-series", "7.1",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lock = json.loads((output_dir / "patch-lock.json").read_text(encoding="utf-8"))
            record = lock["components"]["bore"]
            self.assertEqual(record["selection"], "exact")
            self.assertEqual(record["selected_path"], selected_path)
            self.assertEqual(record["project_version"], "6.8.0")
            self.assertRegex(record["commit"], r"^[0-9a-f]{40}$")
            self.assertEqual(record["sha256"], hashlib.sha256(source.encode()).hexdigest())
            self.assertEqual((output_dir / record["output"]).read_text(), source)

'''
if text.count(old) != 1:
    raise SystemExit(f"legacy approved SHA test matched {text.count(old)} times")
path.write_text(text.replace(old, new), encoding="utf-8")

bore_test = root / "tests/test_bore_liquorix_port.py"
bore_text = bore_test.read_text(encoding="utf-8")
old_regex = '            r"bore-([0-9]+(?:\\.[0-9]+){1,2}(?:-rc[0-9]+)?)\\.patch$",\n'
new_regex = '            r"bore[-_]?([0-9]+(?:\\.[0-9]+)+(?:-rc[0-9]+)?)",\n'
if bore_text.count(old_regex) != 1:
    raise SystemExit(f"BORE manifest regex assertion matched {bore_text.count(old_regex)} times")
bore_test.write_text(bore_text.replace(old_regex, new_regex), encoding="utf-8")

Path(__file__).unlink()
