#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


resolver = Path("scripts/resolve-patch-sources.py")
text = resolver.read_text(encoding="utf-8")
block = '''def kernel_distance(target: KernelVersion, kernel: KernelVersion) -> int:
    left = target.parts + (0,) * (3 - len(target.parts))
    right = kernel.parts + (0,) * (3 - len(kernel.parts))
    return (
        abs(left[0] - right[0]) * 1_000_000
        + abs(left[1] - right[1]) * 1_000
        + abs(left[2] - right[2])
    )


def compatibility_score(target: KernelVersion | None, kernel: KernelVersion) -> tuple[int, int]:
    if target is None:
        return 4, 0
    distance_rank = -kernel_distance(target, kernel)
    if target.parts == kernel.parts:
        return 6, distance_rank
    if target.series == kernel.series:
        return 5, distance_rank
    # If no same-series source exists, either direction can be a valid porting
    # base. Prefer the numerically closest kernel instead of the highest path.
    return 3, distance_rank


def candidate_score(path: str, kernel: KernelVersion, version_pattern: str | None) -> tuple[Any, ...]:
    target = extract_kernel_target(path)
    compat_rank, distance_rank = compatibility_score(target, kernel)
    channel_rank = 2 if "/stable/" in f"/{path}" else 1 if "/testing/" in f"/{path}" else 0
    version = project_version(path, version_pattern)
    return compat_rank, distance_rank, version_key(version), channel_rank, path


'''
pattern = re.compile(r"def compatibility_score\(.*?(?=def match_paths\()", re.DOTALL)
text, count = pattern.subn(block, text, count=1)
if count != 1:
    raise SystemExit(f"resolver scoring block: expected one match, found {count}")
resolver.write_text(text, encoding="utf-8")

reflex = Path("scripts/apply-reflex-core.py")
text = reflex.read_text(encoding="utf-8")
for old, new, label in (
    ('"""Inject the pinned REFLEX CPUFreq patch into the CI build pipeline."""',
     '"""Inject the dynamic REFLEX CPUFreq bootstrap into the CI build pipeline."""',
     "REFLEX docstring"),
    ('if \'REFLEX_COMMIT="a7a7774b059a1f913521ffbfc52eeda72bdbb14c"\' in source:',
     'if "# REFLEX CPUFreq dynamic bootstrap" in source:',
     "REFLEX idempotency"),
    ('# REFLEX CPUFreq: native Linux 7.1 patch, pinned to an exact upstream commit.',
     '# REFLEX CPUFreq dynamic bootstrap. The patch lock replaces these current defaults.',
     "REFLEX bootstrap comment"),
    ('REFLEX_COMMIT="a7a7774b059a1f913521ffbfc52eeda72bdbb14c"',
     'REFLEX_COMMIT="a7205405c20a499fc1490e073fab03dc9a28e818"',
     "REFLEX commit"),
    ('REFLEX_PATCH_PATH="patches/0001-linux7.1-reflex-v0.3.1.patch"',
     'REFLEX_PATCH_PATH="patches/0001-linux7.1-reflex-v0.3.2.patch"',
     "REFLEX path"),
    ('REFLEX_PATCH="$PATCHDIR/0007-reflex-v0.3.1-linux7.1.patch"',
     'REFLEX_PATCH="$PATCHDIR/0007-reflex-linux7.1.patch"\nPATCH_REFLEX_VERSION="${PATCH_REFLEX_VERSION:-0.3.2}"',
     "REFLEX version variable"),
    ('echo "==> Fetching pinned REFLEX CPUFreq 0.3.1 source locally"',
     'echo "==> Fetching REFLEX CPUFreq $PATCH_REFLEX_VERSION source locally"',
     "REFLEX fetch message"),
    ("grep -Fq 'Subject: [PATCH] linux7.1-reflex-v0.3.1' \"$REFLEX_PATCH\"",
     "grep -Fqi 'reflex' \"$REFLEX_PATCH\"",
     "REFLEX patch validation"),
    ('echo "Component: REFLEX CPUFreq Governor 0.3.1"',
     'echo "Component: REFLEX CPUFreq Governor $PATCH_REFLEX_VERSION"',
     "REFLEX provenance"),
    ('echo "Acquisition: pinned local partial Git checkout"',
     'echo "Acquisition: dynamically locked local partial Git checkout"',
     "REFLEX acquisition"),
    ('echo "==> Applying native Linux 7.1 REFLEX CPUFreq 0.3.1 patch"',
     'echo "==> Applying Linux 7.1 REFLEX CPUFreq $PATCH_REFLEX_VERSION patch"',
     "REFLEX apply message"),
    ('grep -Fq \'#define CPUFREQ_REFLEX_VERSION  "0.3.1"\' drivers/cpufreq/cpufreq_reflex.c',
     '[[ "$PATCH_REFLEX_VERSION" == "unknown" ]] || grep -Fq "$PATCH_REFLEX_VERSION" drivers/cpufreq/cpufreq_reflex.c',
     "REFLEX runtime version"),
    ('echo "==> REFLEX 0.3.1 patch and default-governor integration applied successfully"',
     'echo "==> REFLEX $PATCH_REFLEX_VERSION patch and default-governor integration applied successfully"',
     "REFLEX success message"),
):
    text = replace_once(text, old, new, label)
text = re.sub(
    r"The 0\.3\.1\n\s+# patch does not add the symbol to the default-governor choice, so complete",
    "If the selected patch does not add the symbol to the default-governor\n   # choice, complete",
    text,
    count=1,
)
if "drivers/base/arch_topology.c" not in text:
    text = replace_once(
        text,
        "    arch/x86/kernel/cpu/aperfmperf.c \\\n    drivers/cpufreq \\",
        "    arch/x86/kernel/cpu/aperfmperf.c \\\n    drivers/base/arch_topology.c \\\n    drivers/cpufreq \\",
        "REFLEX diff coverage",
    )
reflex.write_text(text, encoding="utf-8")

manifest = Path("config/patch-sources.json")
text = manifest.read_text(encoding="utf-8")
text = replace_once(
    text,
    "patches/testing/0001-linux{series}-rc*-bore-*.patch",
    "patches/testing/0001-linux{series}*-bore-*.patch",
    "BORE testing glob",
)
text = replace_once(
    text,
    "patches/stable/linux-{series}-bore/0001-linux{series}-rc*-bore-*.patch",
    "patches/stable/linux-{series}-bore/0001-linux{series}*-bore-*.patch",
    "BORE stable glob",
)
manifest.write_text(text, encoding="utf-8")

tests = Path("tests/test_dynamic_patch_resolver.py")
text = tests.read_text(encoding="utf-8")
if "test_nearest_fallback_prefers_distance_over_newest_kernel" not in text:
    anchor = "    def test_fallback_ref_restores_exact_series(self) -> None:\n"
    addition = '''    def test_nearest_fallback_prefers_distance_over_newest_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            init_repo(
                repo,
                {
                    "patches/stable/0001-linux7.2-demo-v1.0.patch": patch("demo 1.0"),
                    "patches/stable/0001-linux7.9-demo-v9.0.patch": patch("demo 9.0"),
                    "patches/stable/0001-linux7.0-demo-v2.0.patch": patch("demo 2.0"),
                },
            )
            manifest = {
                "schema": 1,
                "components": {
                    "demo": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/stable/*linux{series}*demo*.patch"],
                        "fallback_globs": ["patches/stable/*demo*.patch"],
                        "require_exact_series": False,
                        "output": "demo.patch",
                        "project_version_regex": r"demo-v([0-9.]+)",
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = tmp / "resolved"
            run(
                "python3", str(RESOLVER), "--manifest", str(manifest_path),
                "--output-dir", str(output), "--kernel-version", "7.1.3",
                "--kernel-series", "7.1",
            )
            record = json.loads((output / "patch-lock.json").read_text())["components"]["demo"]
            self.assertIn("linux7.2", record["selected_path"])
            self.assertEqual(record["project_version"], "1.0")

'''
    text = replace_once(text, anchor, addition + anchor, "nearest fallback test")
    tests.write_text(text, encoding="utf-8")

Path("tests/test_reflex_dynamic_bootstrap.py").write_text(
    '''#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReflexBootstrapTests(unittest.TestCase):
    def test_bootstrap_is_current_and_runtime_checks_are_dynamic(self) -> None:
        source = (ROOT / "scripts/apply-reflex-core.py").read_text(encoding="utf-8")
        self.assertIn("a7205405c20a499fc1490e073fab03dc9a28e818", source)
        self.assertIn("patches/0001-linux7.1-reflex-v0.3.2.patch", source)
        self.assertIn('PATCH_REFLEX_VERSION="${PATCH_REFLEX_VERSION:-0.3.2}"', source)
        self.assertIn('grep -Fq "$PATCH_REFLEX_VERSION" drivers/cpufreq/cpufreq_reflex.c', source)
        self.assertIn("drivers/base/arch_topology.c", source)
        self.assertNotIn('CPUFREQ_REFLEX_VERSION  "0.3.1"', source)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)
