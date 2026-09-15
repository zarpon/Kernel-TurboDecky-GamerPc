#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = "__DYNAMIC_PATCH_LOCK_REQUIRED__"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text and old not in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# The BORE finalizer only needs to prove that both the version symbol and the
# dynamic locked version variable survive in the generic source contract.
base = ROOT / "scripts/finalize-bore-stable-port-base.py"
text = base.read_text(encoding="utf-8")
text = text.replace(
    "        'SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"',\n",
    "        'SCHED_BORE_VERSION',\n        '$BORE_PORT_VERSION',\n",
)
base.write_text(text, encoding="utf-8")

# Package identity is supplied by resolve-latest-stable.py for the selected
# newest upstream kernel; do not retain an old Debian version in the template.
core = ROOT / "scripts/build-kernelnote-core.sh"
text = core.read_text(encoding="utf-8")
text = text.replace(
    'KDEB_PKGVERSION="7.1.4-1turbodecky1"',
    'KDEB_PKGVERSION="${KERNEL_DEB_VERSION:?KERNEL_DEB_VERSION must be resolved}"',
)
text = text.replace(
    "Acquisition: pinned current-upstream partial Git checkout; no local fallback",
    "Acquisition: authenticated current-upstream lock; no local fallback",
)
core.write_text(text, encoding="utf-8")

# Update tests to assert the new lock-only source contract rather than old
# bootstrap identities.
marie = ROOT / "tests/test_marie_version_reporting.py"
text = marie.read_text(encoding="utf-8")
text = text.replace(
    "Fetching pinned Marie LRU $PATCH_MARIE_VERSION testing source locally",
    "Fetching current locked Marie LRU $PATCH_MARIE_VERSION testing source locally",
)
marie.write_text(text, encoding="utf-8")

reflex = ROOT / "tests/test_reflex_dynamic_bootstrap.py"
reflex.write_text(f'''#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReflexBootstrapTests(unittest.TestCase):
    def test_bootstrap_is_lock_only_and_runtime_checks_are_dynamic(self) -> None:
        source = (ROOT / "scripts/apply-reflex-core.py").read_text(encoding="utf-8")
        self.assertIn('REFLEX_REPO="{LOCK}"', source)
        self.assertIn('REFLEX_COMMIT="{LOCK}"', source)
        self.assertIn('REFLEX_PATCH_PATH="{LOCK}"', source)
        self.assertIn('PATCH_REFLEX_VERSION="{LOCK}"', source)
        self.assertIn('REFLEX_PATCH="$PATCHDIR/0007-reflex-current.patch"', source)
        self.assertIn('grep -Fq "$PATCH_REFLEX_VERSION" drivers/cpufreq/cpufreq_reflex.c', source)
        self.assertIn("drivers/base/arch_topology.c", source)
        self.assertNotIn("a7205405c20a499fc1490e073fab03dc9a28e818", source)
        self.assertNotIn("linux7.1-reflex-v0.3.2", source)
        self.assertNotIn('CPUFREQ_REFLEX_VERSION  "0.3.1"', source)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")
