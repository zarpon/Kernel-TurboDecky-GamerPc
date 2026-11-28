#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REWRITER = ROOT / "scripts/apply-zen-interactive.py"
RESOLVER = ROOT / "scripts/resolve-zen-interactive.py"
CORE = ROOT / "scripts/build-kernelnote-core.sh"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


rewriter = load("apply_zen_interactive", REWRITER)
resolver = load("resolve_zen_interactive", RESOLVER)


class ZenInteractiveRewriterTests(unittest.TestCase):
    def test_rewriter_integrates_official_profile_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text(CORE.read_text(encoding="utf-8"), encoding="utf-8")
            rewriter.rewrite(path)
            result = path.read_text(encoding="utf-8")
            self.assertIn(
                'ZEN_INTERACTIVE_REF="${KERNEL_SERIES:-7.1}/zen-sauce"', result
            )
            self.assertIn("compatibility commits", result)
            self.assertIn("fetch_zen_interactive_profile", result)
            self.assertIn("apply_zen_interactive_profile", result)
            self.assertIn("assert_zen_patch_does_not_touch_thp", result)
            self.assertIn("00-zen-interactive-thp-preserved.sha256", result)
            self.assertIn("scripts/config --enable ZEN_INTERACTIVE", result)
            self.assertIn('assert_config "CONFIG_ZEN_INTERACTIVE=y"', result)
            rewriter.rewrite(path)
            self.assertEqual(result, path.read_text(encoding="utf-8"))

    def test_rewriter_survives_prior_fetch_injections(self) -> None:
        original = CORE.read_text(encoding="utf-8")
        old = 'fetch_bore_sched_ext_source\n'
        self.assertEqual(original.count(old), 1)
        transformed = original.replace(
            old,
            old + "fetch_requested_patch_series\nfetch_reflex_patch\n",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text(transformed, encoding="utf-8")
            rewriter.rewrite(path)
            result = path.read_text(encoding="utf-8")
            self.assertIn(
                "fetch_requested_patch_series\nfetch_reflex_patch\n"
                'download "$ADIOS_URL" "$PATCHDIR/0003-adios-current.patch"\n\n'
                "fetch_zen_interactive_profile\n\ncd \"$KERNELDIR\"",
                result,
            )

    def test_rewriter_does_not_depend_on_a_sched_ext_digest_anchor(self) -> None:
        original = CORE.read_text(encoding="utf-8")
        original = original.replace(
            'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256='
            '"__DYNAMIC_PATCH_LOCK_REQUIRED__"',
            'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="new-lock-digest"',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text(original, encoding="utf-8")
            rewriter.rewrite(path)
            result = path.read_text(encoding="utf-8")

        self.assertIn('BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="new-lock-digest"', result)
        self.assertIn('ZEN_INTERACTIVE_REF="${KERNEL_SERIES:-7.1}/zen-sauce"', result)

    def test_rewriter_rejects_missing_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text("echo no anchors\n", encoding="utf-8")
            with self.assertRaises(rewriter.RewriteError):
                rewriter.rewrite(path)

    def test_resolver_keeps_symbol_hunks_and_excludes_thp(self) -> None:
        diff = """diff --git a/init/Kconfig b/init/Kconfig
index 1111111111111111111111111111111111111111..2222222222222222222222222222222222222222 100644
--- a/init/Kconfig
+++ b/init/Kconfig
@@ -1,2 +1,8 @@
 menu \"General setup\"
+config ZEN_INTERACTIVE
+\tbool \"Tune kernel for interactivity\"
+\tdefault y
+\thelp
+\t    Background-reclaim hugepages...: no -> yes
+
 config OTHER
diff --git a/mm/page_alloc.c b/mm/page_alloc.c
index 3333333333333333333333333333333333333333..4444444444444444444444444444444444444444 100644
--- a/mm/page_alloc.c
+++ b/mm/page_alloc.c
@@ -1,2 +1,4 @@
+#ifdef CONFIG_ZEN_INTERACTIVE
+#define DEFAULT_BOOST 0
+#endif
 value
diff --git a/mm/huge_memory.c b/mm/huge_memory.c
index 5555555555555555555555555555555555555555..6666666666666666666666666666666666666666 100644
--- a/mm/huge_memory.c
+++ b/mm/huge_memory.c
@@ -1,2 +1,6 @@
+#ifdef CONFIG_ZEN_INTERACTIVE
+#define THP_DEFAULT CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS
+#endif
 value
"""
        filtered, files, hunks, excluded = resolver.filter_symbol_hunks(diff)
        self.assertEqual(files, ["init/Kconfig", "mm/page_alloc.c"])
        self.assertEqual(hunks, 2)
        self.assertEqual(excluded, 1)
        self.assertIn("config ZEN_INTERACTIVE", filtered)
        self.assertIn("CONFIG_ZEN_INTERACTIVE", filtered)
        self.assertIn("Transparent memory-page policy....: unchanged", filtered)
        self.assertNotIn("mm/huge_memory.c", filtered)
        self.assertNotIn("TRANSPARENT_HUGEPAGE", filtered)
        self.assertNotIn("THP_DEFAULT", filtered)
        resolver.assert_thp_untouched(filtered)

    def test_thp_guard_rejects_functional_thp_changes(self) -> None:
        patch = """diff --git a/mm/Kconfig b/mm/Kconfig
--- a/mm/Kconfig
+++ b/mm/Kconfig
@@ -1 +1 @@
-CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y
+CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS=y
"""
        with self.assertRaises(resolver.ResolveError):
            resolver.assert_thp_untouched(patch)

    def test_resolver_discovers_only_introduction_commit_files(self) -> None:
        paths = "init/Kconfig\nmm/page_alloc.c\nREADME\n"
        contents = {
            "init/Kconfig": "config ZEN_INTERACTIVE\n",
            "mm/page_alloc.c": "#ifdef CONFIG_ZEN_INTERACTIVE\n#endif\n",
            "README": "unrelated\n",
        }

        def read_file_at(_checkout: Path, _head: str, path: str) -> str:
            return contents[path]

        with mock.patch.object(resolver, "run", return_value=paths) as run_mock:
            with mock.patch.object(resolver, "read_file_at", side_effect=read_file_at):
                selected = resolver.discover_symbol_files(
                    Path("checkout"), intro="intro", head="head"
                )

        self.assertEqual(selected, ["init/Kconfig", "mm/page_alloc.c"])
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:2], ["git", "diff-tree"])
        self.assertNotIn("grep", command)

    def test_resolver_prefers_exact_series_and_falls_back_to_older_series(self) -> None:
        refs = """a refs/heads/7.0/zen-sauce
b refs/heads/7.1/zen-sauce
c refs/heads/6.18/zen-sauce
"""
        with mock.patch.object(resolver, "run", return_value=refs):
            self.assertEqual(
                resolver.select_compatible_ref("7.1"),
                ("7.1/zen-sauce", "7.1", "exact-series"),
            )
        with mock.patch.object(resolver, "run", return_value=refs):
            self.assertEqual(
                resolver.select_compatible_ref("7.2"),
                ("7.1/zen-sauce", "7.1", "nearest-older-series"),
            )

    def test_resolver_materializes_current_compatibility_commits(self) -> None:
        patches = {
            "drivers/input/evdev.c": """diff --git a/drivers/input/evdev.c b/drivers/input/evdev.c
--- a/drivers/input/evdev.c
+++ b/drivers/input/evdev.c
@@ -1 +1 @@
-old
+call_rcu(&client->rcu, evdev_reclaim_client);
""",
            "drivers/cpufreq/Kconfig.x86": """diff --git a/drivers/cpufreq/Kconfig.x86 b/drivers/cpufreq/Kconfig.x86
--- a/drivers/cpufreq/Kconfig.x86
+++ b/drivers/cpufreq/Kconfig.x86
@@ -1 +1 @@
-select CPU_FREQ_GOV_SCHEDUTIL
+# dependency removed for REFLEX
""",
        }

        def fake_run(args, **_kwargs):
            if args[1] == "log":
                return "commit-" + args[-1].replace("/", "-") + "\n"
            if args[1] == "rev-parse":
                return "parent\n"
            if args[1] == "diff":
                return patches[args[-1]]
            if args[1] == "show":
                return "ZEN compatibility commit\n"
            raise AssertionError(args)

        with mock.patch.object(resolver, "run", side_effect=fake_run):
            sources = resolver.discover_compatibility_sources(
                Path("checkout"), head="head"
            )

        self.assertEqual(
            [source["name"] for source in sources],
            ["evdev-call-rcu", "cpufreq-pstate-schedutil-dependency"],
        )
        self.assertTrue(all(source["sha256"] for source in sources))
        self.assertIn("call_rcu(&client->rcu", sources[0]["patch"])
        self.assertIn("CPU_FREQ_GOV_SCHEDUTIL", sources[1]["patch"])

    def test_resolver_main_writes_patch_lock_and_provenance(self) -> None:
        profile = resolver.ProfileResolution(
            patch="diff --git a/init/Kconfig b/init/Kconfig\n",
            head="head",
            intro="intro",
            base="base",
            ref="7.1/zen-sauce",
            kernel_target="7.1",
            files=["drivers/input/evdev.c", "init/Kconfig"],
            hunks=2,
            profile_hunks=1,
            excluded_thp_hunks=1,
            compatibility_sources=[
                {
                    "name": "evdev-call-rcu",
                    "path": "drivers/input/evdev.c",
                    "commit": "compat",
                    "parent_commit": "parent",
                    "subject": "compatibility",
                    "selection": "latest matching commit on selected official Zen series",
                    "sha256": "digest",
                    "size": 12,
                    "patch": "diff --git a/drivers/input/evdev.c b/drivers/input/evdev.c\n",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "zen.patch"
            provenance = root / "zen.provenance"
            lock = root / "patch-lock.json"
            lock.write_text('{"components": {}}\n', encoding="utf-8")
            argv = sys.argv
            sys.argv = [
                "resolve-zen-interactive.py",
                "--checkout",
                str(root / "checkout"),
                "--output",
                str(output),
                "--provenance",
                str(provenance),
                "--lock",
                str(lock),
            ]
            try:
                with mock.patch.object(resolver, "fetch_profile", return_value=profile):
                    resolver.main()
            finally:
                sys.argv = argv

            self.assertEqual(output.read_text(encoding="utf-8"), profile.patch)
            self.assertIn("Compatibility commit: evdev-call-rcu", provenance.read_text())
            record = json.loads(lock.read_text(encoding="utf-8"))["components"][
                "zen_interactive"
            ]
            self.assertEqual(record["compatibility_sources"][0]["commit"], "compat")
            self.assertNotIn("patch", record["compatibility_sources"][0])

    def test_resolver_fetch_profile_composes_a_local_series_checkout(self) -> None:
        def git(*args: str, cwd: Path) -> None:
            subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "zen.git"
            repo.mkdir()
            git("init", "--quiet", cwd=repo)
            git("config", "user.email", "test@example.invalid", cwd=repo)
            git("config", "user.name", "test", cwd=repo)

            files = {
                "init/Kconfig": "menu General\n",
                "mm/page_alloc.c": "int page_alloc;\n",
                "drivers/input/evdev.c": (
                    "static void evdev_detach_client(void)\n"
                    "{\n"
                    "\tsynchronize_rcu();\n"
                    "}\n"
                ),
                "drivers/cpufreq/Kconfig.x86": (
                    "config X86_PSTATE\n"
                    "\tselect CPU_FREQ_GOV_SCHEDUTIL\n"
                ),
            }
            for relative, content in files.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            git("add", ".", cwd=repo)
            git("commit", "-qm", "base", cwd=repo)

            (repo / "init/Kconfig").write_text(
                "menu General\n"
                "config ZEN_INTERACTIVE\n"
                '\tbool "Tune interactivity"\n'
                "\tdefault y\n",
                encoding="utf-8",
            )
            (repo / "mm/page_alloc.c").write_text(
                "int page_alloc;\n"
                "#ifdef CONFIG_ZEN_INTERACTIVE\n"
                "int zen_page_alloc;\n"
                "#endif\n",
                encoding="utf-8",
            )
            git("add", ".", cwd=repo)
            git("commit", "-qm", "introduce Zen interactive profile", cwd=repo)

            (repo / "drivers/input/evdev.c").write_text(
                "static void evdev_reclaim_client(void) {}\n"
                "static void evdev_detach_client(void)\n"
                "{\n"
                "\tcall_rcu(&client->rcu, evdev_reclaim_client);\n"
                "}\n",
                encoding="utf-8",
            )
            git("add", ".", cwd=repo)
            git("commit", "-qm", "evdev call_rcu", cwd=repo)

            (repo / "drivers/cpufreq/Kconfig.x86").write_text(
                "config X86_PSTATE\n",
                encoding="utf-8",
            )
            git("add", ".", cwd=repo)
            git("commit", "-qm", "remove schedutil dependency", cwd=repo)
            git("update-ref", "refs/heads/7.1/zen-sauce", "HEAD", cwd=repo)

            checkout = root / "checkout"
            original_repo = resolver.REPO
            resolver.REPO = str(repo)
            try:
                with mock.patch.dict(os.environ, {"KERNEL_SERIES": "7.1"}):
                    resolution = resolver.fetch_profile(checkout)
            finally:
                resolver.REPO = original_repo

            self.assertEqual(resolution.ref, "7.1/zen-sauce")
            self.assertEqual(
                [source["name"] for source in resolution.compatibility_sources],
                ["evdev-call-rcu", "cpufreq-pstate-schedutil-dependency"],
            )
            self.assertIn("config ZEN_INTERACTIVE", resolution.patch)
            self.assertIn("call_rcu(&client->rcu", resolution.patch)
            self.assertIn("CPU_FREQ_GOV_SCHEDUTIL", resolution.patch)

    def test_resolver_has_bounded_commands_and_total_deadline(self) -> None:
        source = RESOLVER.read_text(encoding="utf-8")
        self.assertIn("TOTAL_RESOLVE_TIMEOUT = 600", source)
        self.assertIn("REMOTE_FETCH_RETRIES = 3", source)
        self.assertIn('REMOTE_LOW_SPEED_TIME = "120"', source)
        self.assertIn("subprocess.TimeoutExpired", source)
        self.assertIn('f"{intro}^"', source)
        self.assertIn("git", source)
        self.assertIn("compatibility_sources", source)
        self.assertNotIn('["git", "grep", "-l", SYMBOL, head, "--"]', source)

    def test_resolver_retries_transient_promisor_blob_failures(self) -> None:
        transient = resolver.ResolveError(
            "command failed (128): git show HEAD:init/Kconfig\n"
            "fatal: unable to access 'https://github.com/zen-kernel/zen-kernel.git/': "
            "Operation too slow. Less than 1024 bytes/sec transferred the last 30 seconds"
        )
        with mock.patch.object(
            resolver,
            "run",
            side_effect=[transient, "config ZEN_INTERACTIVE\n"],
        ) as run_mock, mock.patch.object(resolver.time, "sleep") as sleep_mock:
            content = resolver.read_file_at(
                Path("checkout"), "HEAD", "init/Kconfig"
            )

        self.assertEqual(content, "config ZEN_INTERACTIVE\n")
        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once_with(resolver.REMOTE_RETRY_DELAY_SECONDS)

    def test_resolver_does_not_retry_permanent_blob_errors(self) -> None:
        permanent = resolver.ResolveError(
            "command failed (128): git show HEAD:missing\n"
            "fatal: path 'missing' does not exist in 'HEAD'"
        )
        with mock.patch.object(resolver, "run", side_effect=permanent) as run_mock:
            with self.assertRaises(resolver.ResolveError):
                resolver.read_file_at(Path("checkout"), "HEAD", "missing")

        self.assertEqual(run_mock.call_count, 1)

    def test_resolver_retries_the_same_branch_listing_after_timeout(self) -> None:
        failure = resolver.ResolveError("command timed out after 180s: git ls-remote")
        refs = "a refs/heads/7.3/zen-sauce\nb refs/heads/7.2/zen-sauce\n"
        with mock.patch.object(resolver, "run", side_effect=[failure, refs]) as run_mock:
            with mock.patch.object(resolver.time, "sleep"):
                selected = resolver.select_compatible_ref("7.3")
        self.assertEqual(selected, ("7.3/zen-sauce", "7.3", "exact-series"))
        self.assertEqual(run_mock.call_args_list[0], run_mock.call_args_list[1])

    def test_resolver_stops_after_bounded_transport_retries(self) -> None:
        failure = resolver.ResolveError("Operation too slow")
        with mock.patch.object(resolver, "run", side_effect=failure) as run_mock:
            with mock.patch.object(resolver.time, "sleep") as sleep_mock:
                with self.assertRaisesRegex(resolver.ResolveError, "Operation too slow"):
                    resolver.run_remote(["git", "fetch", "origin", "refs/heads/7.3/zen-sauce"])
        self.assertEqual(run_mock.call_count, resolver.REMOTE_FETCH_RETRIES)
        self.assertEqual(sleep_mock.call_count, resolver.REMOTE_FETCH_RETRIES - 1)

    def test_resolver_recovers_multiple_exact_blobs_for_one_history_command(self) -> None:
        oids = ["1" * 40, "2" * 40]
        failures = [resolver.ResolveError(
            f"Operation too slow\nfatal: could not fetch {oid} from promisor remote"
        ) for oid in oids]
        command = ["git", "log", "-G", "ZEN_INTERACTIVE", "FETCH_HEAD"]
        with mock.patch.object(resolver, "run", side_effect=failures + ["current commit\n"]) as run_mock:
            with mock.patch.object(resolver, "recover_promisor_blob") as recover:
                self.assertEqual(
                    resolver.run_remote(command, cwd=Path("checkout")), "current commit\n"
                )
        self.assertEqual(recover.call_args_list, [mock.call(Path("checkout"), oid) for oid in oids])
        self.assertTrue(all(call.args[0] == command for call in run_mock.call_args_list))

    def test_resolver_caps_distinct_promisor_recoveries(self) -> None:
        failures = [resolver.ResolveError(
            f"Operation too slow\nfatal: could not fetch {digit * 40} from promisor remote"
        ) for digit in "123"]
        with mock.patch.object(resolver, "MAX_PROMISOR_RECOVERIES", 2):
            with mock.patch.object(resolver, "run", side_effect=failures):
                with mock.patch.object(resolver, "recover_promisor_blob") as recover:
                    with self.assertRaisesRegex(resolver.ResolveError, "recovery limit"):
                        resolver.run_remote(["git", "diff", "base", "head"], cwd=Path("checkout"))
        self.assertEqual(recover.call_count, 2)

    def test_resolver_verifies_and_imports_blob_without_logging_api_token(self) -> None:
        content = b"config ZEN_INTERACTIVE\n\tbool \"Tune interactivity\"\n"
        oid = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        token = "zen-test-credential-do-not-log"
        original_run = resolver.run
        headers_seen = []

        def fake_download(args, **kwargs):
            if args[0] != "curl":
                return original_run(args, **kwargs)
            self.assertEqual(args[-1], f"https://api.github.com/repos/zen-kernel/zen-kernel/git/blobs/{oid}")
            self.assertNotIn(token, " ".join(args))
            headers = Path(next(arg[1:] for arg in args if arg.startswith("@")))
            self.assertEqual(headers.read_text(), f"Authorization: Bearer {token}\n")
            self.assertEqual(headers.stat().st_mode & 0o777, 0o600)
            headers_seen.append(headers)
            Path(args[args.index("--output") + 1]).write_bytes(content)
            return ""

        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            output = io.StringIO()
            with mock.patch.dict(os.environ, {"ZEN_GITHUB_TOKEN": token}):
                with mock.patch.object(resolver, "run", side_effect=fake_download):
                    with contextlib.redirect_stdout(output):
                        resolver.recover_promisor_blob(checkout, oid)
            actual = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=checkout)
        self.assertEqual(actual, content)
        self.assertNotIn(token, output.getvalue())
        self.assertFalse(headers_seen[0].exists())

    def test_resolver_rejects_blob_hash_mismatch_before_import(self) -> None:
        def fake_download(args, **_kwargs):
            self.assertEqual(args[0], "curl")
            Path(args[args.index("--output") + 1]).write_bytes(b"wrong blob or error page")
            return ""
        with mock.patch.object(resolver, "run", side_effect=fake_download) as run_mock:
            with self.assertRaisesRegex(resolver.ResolveError, "blob hash mismatch"):
                resolver.recover_promisor_blob(Path("checkout"), "1" * 40)
        self.assertEqual(run_mock.call_count, 1)

    def test_resolver_does_not_replace_an_unavailable_blob(self) -> None:
        failure = resolver.ResolveError("curl: (22) The requested URL returned error: 404")
        with mock.patch.object(resolver, "run", side_effect=failure) as run_mock:
            with self.assertRaisesRegex(resolver.ResolveError, "404"):
                resolver.recover_promisor_blob(Path("checkout"), "1" * 40)
        self.assertEqual(run_mock.call_count, 1)

    def test_resolver_deepens_only_for_insufficient_history(self) -> None:
        for error, expected_fetches in [
            (resolver.ResolveError("Operation too slow"), 1),
            (resolver.InsufficientHistory("compatibility commit outside depth"), 2),
        ]:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(resolver, "MAX_HISTORY_DEPTH", 256), \
                     mock.patch.object(resolver, "select_compatible_ref", return_value=("7.3/zen-sauce", "7.3", "exact-series")), \
                     mock.patch.object(resolver, "run", return_value="") as run_mock, \
                     mock.patch.object(resolver, "locate_introduction", return_value="intro"), \
                     mock.patch.object(resolver.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                     mock.patch.object(resolver, "discover_compatibility_sources", side_effect=error):
                    with self.assertRaises(type(error)):
                        resolver.fetch_profile(Path(directory) / "checkout")
                fetches = [call.args[0] for call in run_mock.call_args_list if call.args[0][1] == "fetch"]
                self.assertEqual(len(fetches), expected_fetches)
                self.assertTrue(all(args[-1] == "refs/heads/7.3/zen-sauce" for args in fetches))

    def test_resolver_reports_missing_compatibility_history_explicitly(self) -> None:
        with mock.patch.object(resolver, "run_remote", return_value=""):
            with self.assertRaises(resolver.InsufficientHistory):
                resolver.discover_compatibility_sources(Path("checkout"), head="FETCH_HEAD")


if __name__ == "__main__":
    unittest.main()
