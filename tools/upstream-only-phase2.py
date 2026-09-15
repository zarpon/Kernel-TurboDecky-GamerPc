#!/usr/bin/env python3
from __future__ import annotations

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


def neutralize_reflex() -> None:
    path = ROOT / "scripts/apply-reflex-core.py"
    text = path.read_text(encoding="utf-8")
    replacements = {
        'REFLEX_REPO="https://github.com/firelzrd/reflex.git"': f'REFLEX_REPO="{LOCK}"',
        'REFLEX_COMMIT="a7205405c20a499fc1490e073fab03dc9a28e818"': f'REFLEX_COMMIT="{LOCK}"',
        'REFLEX_PATCH_PATH="patches/0001-linux7.1-reflex-v0.3.2.patch"': f'REFLEX_PATCH_PATH="{LOCK}"',
        'REFLEX_PATCH="$PATCHDIR/0007-reflex-linux7.1.patch"': 'REFLEX_PATCH="$PATCHDIR/0007-reflex-current.patch"',
        'PATCH_REFLEX_VERSION="${PATCH_REFLEX_VERSION:-0.3.2}"': f'PATCH_REFLEX_VERSION="{LOCK}"',
        'echo "==> Applying Linux 7.1 REFLEX CPUFreq $PATCH_REFLEX_VERSION patch"': 'echo "==> Applying current upstream REFLEX CPUFreq $PATCH_REFLEX_VERSION to Linux $KERNEL_VERSION"',
        'if [[ "$PATCH_REFLEX_VERSION" != "unknown" ]]; then': 'if [[ "$PATCH_REFLEX_VERSION" != "__DYNAMIC_PATCH_LOCK_REQUIRED__" ]]; then',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            raise SystemExit(f"REFLEX cleanup anchor missing: {old}")
    text = text.replace(
        "# REFLEX CPUFreq dynamic bootstrap. The patch lock replaces these current defaults.",
        "# REFLEX CPUFreq dynamic bootstrap. Every source identity is supplied by the authenticated patch lock.",
    )
    path.write_text(text, encoding="utf-8")


def neutralize_vram() -> None:
    path = ROOT / "scripts/apply-vram-cgroup.py"
    text = path.read_text(encoding="utf-8")
    replacements = {
        'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"': 'NAP_PATCH="$PATCHDIR/0006-nap-current-port.patch"',
        'VRAM_PATCH_REPO="https://github.com/CachyOS/kernel-patches.git"': f'VRAM_PATCH_REPO="{LOCK}"',
        'VRAM_PATCH_COMMIT="ea739d734ec179864b21446856315bc49f7c52fa"': f'VRAM_PATCH_COMMIT="{LOCK}"',
        'VRAM_PATCH_PATH="7.0/misc/0001-cgroup-vram.patch"': f'VRAM_PATCH_PATH="{LOCK}"',
        'VRAM_PATCH="$PATCHDIR/0007-cgroup-vram-linux7.1-port.patch"': 'VRAM_PATCH="$PATCHDIR/0007-cgroup-vram-current.patch"',
        "# CachyOS aggregation of pixelcluster's six upstream commits, pinned exactly.": "# Current aggregation selected and authenticated by the dynamic patch lock.",
        'echo "==> Fetching pinned VRAM cgroup/TTM patch source"': 'echo "==> Fetching current locked VRAM cgroup/TTM patch source"',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
        elif new not in text:
            raise SystemExit(f"VRAM cleanup anchor missing: {old}")
    path.write_text(text, encoding="utf-8")


def neutralize_core() -> None:
    path = ROOT / "scripts/build-kernelnote-core.sh"
    text = path.read_text(encoding="utf-8")
    replacements = {
        'echo "==> Fetching pinned Marie LRU $PATCH_MARIE_VERSION testing source locally"': 'echo "==> Fetching current locked Marie LRU $PATCH_MARIE_VERSION testing source locally"',
        'echo "==> Fetching the pinned upstream BORE $BORE_PORT_VERSION source locally"': 'echo "==> Fetching current locked upstream BORE $BORE_PORT_VERSION source locally"',
        "grep -Fq 'SCHED_BORE_VERSION  \"6.8.0-rc1\"' \"$BORE_UPSTREAM_PATCH\"": 'grep -Fq "SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"" "$BORE_UPSTREAM_PATCH"',
        "grep -Fq 'sched: port BORE 6.8.0-rc1 to Linux 7.1.4' \"$BORE_PATCH\"": 'grep -Fq "Subject: [PATCH] linux${KERNEL_VERSION}-bore-${BORE_PORT_VERSION}" "$BORE_PATCH"',
        'echo "Acquisition: pinned local partial Git checkout plus reviewed local port"': 'echo "Acquisition: authenticated current-upstream lock plus target compatibility adapter"',
        'echo "==> Fetching the pinned upstream BORE sched_ext coexistence fix"': 'echo "==> Fetching current locked upstream BORE sched_ext coexistence fix"',
        "grep -Fq 'sched: port 0002 sched-ext coexistence fix to Linux 7.1.4' \"$BORE_SCHED_EXT_PATCH\"": 'grep -Fq "Subject: [PATCH] sched: adapt locked sched-ext coexistence fix to Linux $KERNEL_VERSION" "$BORE_SCHED_EXT_PATCH"',
        'echo "==> Applying the reviewed BORE 6.8.0-rc1 Linux 7.1.4 port"': 'echo "==> Applying upstream BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION"',
        'report_bore_rejects "BORE 6.8.0-rc1 for Linux 7.1.4"': 'report_bore_rejects "BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION"',
        "grep -Fq 'SCHED_BORE_VERSION' kernel/sched/bore.c": 'grep -Fq "SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"" include/linux/sched/bore.h',
        'echo "==> BORE 6.8.0-rc1 Linux port applied successfully"': 'echo "==> BORE $BORE_PORT_VERSION Linux port applied successfully"',
        'report_bore_rejects "BORE sched_ext coexistence fix for Linux 7.1.4"': 'report_bore_rejects "BORE sched_ext coexistence fix for Linux $KERNEL_VERSION"',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
        elif new not in text:
            raise SystemExit(f"core cleanup anchor missing: {old}")
    text = text.replace(
        "# Marie is fetched as a pinned local Git checkout rather than through a raw\n# patch URL. Only the exact patch blob is materialized in the workspace.",
        "# Marie is fetched from the authenticated current-upstream lock. Only the exact locked patch blob is materialized.",
    )
    path.write_text(text, encoding="utf-8")


def generic_sched_ext_template() -> None:
    path = ROOT / "patches/bore/sched-ext-coexistence-template.patch"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('''From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\nFrom: TurboDecky Compatibility <noreply@localhost>\nDate: Thu, 1 Jan 1970 00:00:00 +0000\nSubject: [PATCH] sched: compatibility template for locked sched-ext coexistence fix\n\nStructural target adapter. The current authenticated upstream helper body and digest are injected by the BORE finalizer before use.\n\nUpstream-sha256: 0000000000000000000000000000000000000000000000000000000000000000\n---\n include/linux/sched/bore.h |  1 +\n kernel/sched/fair.c        | 12 ++++++++++++\n 2 files changed, 13 insertions(+)\n\ndiff --git a/include/linux/sched/bore.h b/include/linux/sched/bore.h\nindex 92bebc114e..a5b8e6f1d2 100644\n--- a/include/linux/sched/bore.h\n+++ b/include/linux/sched/bore.h\n@@ -45,6 +45,7 @@ extern int  sched_burst_protect_slice_lv_update_handler(const struct ctl_table *\n  * both halves consistent, so BORE drives that instead.\n  */\n+extern void reweight_task(struct task_struct *p, int prio);\n extern void reweight_task_fair(struct rq *rq, struct task_struct *p,\n \t\t\t       const struct load_weight *lw);\n \n #endif /* _KERNEL_SCHED_BORE_H */\ndiff --git a/kernel/sched/fair.c b/kernel/sched/fair.c\nindex ed51ce22d..63d2a6cd8 100644\n--- a/kernel/sched/fair.c\n+++ b/kernel/sched/fair.c\n@@ -14439,3 +14439,15 @@ __init void init_sched_fair_class(void)\n \tzalloc_cpumask_var(&nohz.idle_cpus_mask, GFP_NOWAIT);\n #endif\n }\n+\n+#ifdef CONFIG_SCHED_BORE\n+void reweight_task(struct task_struct *p, int prio)\n+{\n+\tstruct load_weight lw = {\n+\t\t.weight = scale_load(sched_prio_to_weight[prio]),\n+\t\t.inv_weight = sched_prio_to_wmult[prio],\n+\t};\n+\n+\treweight_task_fair(task_rq(p), p, &lw);\n+}\n+#endif /* CONFIG_SCHED_BORE */\n-- \n2.51.1\n''', encoding="utf-8")

    base = ROOT / "scripts/finalize-bore-stable-port-base.py"
    text = base.read_text(encoding="utf-8")
    text = text.replace(
        'SCHED_EXT_PORT_TEMPLATE = ROOT / "patches/bore/7.1.4-sched-ext-coexistence-fix.patch"',
        'SCHED_EXT_PORT_TEMPLATE = ROOT / "patches/bore/sched-ext-coexistence-template.patch"',
    )
    text = text.replace('"Linux 7.1 sched_ext port template"', '"maintained sched_ext compatibility template"')
    text = text.replace(
        r'r"^Subject: \[PATCH\] sched: port 0002 sched-ext coexistence fix to Linux [0-9.]+$"',
        r'r"^Subject: \[PATCH\] sched: compatibility template for locked sched-ext coexistence fix$"',
    )
    text = text.replace('"linux7.1-sched-ext-reweight-task"', '"locked-sched-ext-reweight-task-template"')

    start = text.index("    replacements = (", text.index("def rewrite_core("))
    end_marker = "    path.write_text(text, encoding=\"utf-8\")"
    end = text.index(end_marker, start)
    replacement = '''    assignments = (\n        (r'^BORE_PATCH=.*$', f'BORE_PATCH="$RESOLVED_PATCH_ROOT/{output}"', "BORE patch assignment"),\n        (r'^BORE_PORT_VERSION=.*$', f'BORE_PORT_VERSION="{version}"', "BORE version assignment"),\n        (r'^BORE_PORT_UPSTREAM_SHA256=.*$', f'BORE_PORT_UPSTREAM_SHA256="{sha256}"', "BORE SHA assignment"),\n        (r'^BORE_SCHED_EXT_PORT_UPSTREAM_SHA256=.*$', f'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="{sched_ext_sha256}"', "BORE sched_ext SHA assignment"),\n        (r'^BORE_SCHED_EXT_PATCH=.*$', f'BORE_SCHED_EXT_PATCH="$RESOLVED_PATCH_ROOT/{sched_ext_output}"', "BORE sched_ext port assignment"),\n    )\n    for pattern, replacement, label in assignments:\n        text = replace_regex_once(text, pattern, replacement, label)\n    required = (\n        'SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"',\n        'linux${KERNEL_VERSION}-bore-${BORE_PORT_VERSION}',\n        'sched: adapt locked sched-ext coexistence fix to Linux $KERNEL_VERSION',\n        'Applying upstream BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION',\n        'BORE $BORE_PORT_VERSION Linux port applied successfully',\n    )\n    missing = [marker for marker in required if marker not in text]\n    if missing:\n        raise FinalizeError(f"generated core lost dynamic BORE contract markers: {missing}")\n'''
    text = text[:start] + replacement + text[end:]
    base.write_text(text, encoding="utf-8")


def modernize_finalizer_tests() -> None:
    path = ROOT / "tests/test_bore_stable_finalizer.py"
    text = path.read_text(encoding="utf-8")
    start = text.index("    def test_final_rewrite_uses_locked_upstream_patch(self) -> None:")
    end = text.index("    def test_sched_ext_structural_change_fails_closed", start)
    new = '''    def test_final_rewrite_uses_locked_upstream_patch(self) -> None:\n        with tempfile.TemporaryDirectory() as directory:\n            root = Path(directory)\n            lock_path, record, sched_ext_record = self.make_lock(root)\n            _loaded, upstream = finalizer.load_locked_sched_ext(lock_path, "7.1.5")\n            sched_ext_port = finalizer.materialize_sched_ext_port(\n                lock_path, sched_ext_record, upstream, "7.1.5"\n            )\n            core = root / "build-core.sh"\n            core.write_text(\n                'BORE_PATCH="$PATCHDIR/01-bore-current-port.patch"\\n'\n                'BORE_PORT_VERSION="__DYNAMIC_PATCH_LOCK_REQUIRED__"\\n'\n                'BORE_PORT_UPSTREAM_SHA256="__DYNAMIC_PATCH_LOCK_REQUIRED__"\\n'\n                'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="__DYNAMIC_PATCH_LOCK_REQUIRED__"\\n'\n                'BORE_SCHED_EXT_PATCH="$PATCHDIR/01-bore-sched-ext-current-port.patch"\\n'\n                'grep -Fq "SCHED_BORE_VERSION  \\\\\\"$BORE_PORT_VERSION\\\\\\"" "$BORE_UPSTREAM_PATCH"\\n'\n                'grep -Fq "Subject: [PATCH] linux${KERNEL_VERSION}-bore-${BORE_PORT_VERSION}" "$BORE_PATCH"\\n'\n                'grep -Fq "Subject: [PATCH] sched: adapt locked sched-ext coexistence fix to Linux $KERNEL_VERSION" "$BORE_SCHED_EXT_PATCH"\\n'\n                'echo "==> Applying upstream BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION"\\n'\n                'echo "==> BORE $BORE_PORT_VERSION Linux port applied successfully"\\n',\n                encoding="utf-8",\n            )\n            finalizer.rewrite_core(core, record, sched_ext_record, sched_ext_port, "7.1.5")\n            result = core.read_text(encoding="utf-8")\n            self.assertIn('BORE_PATCH="$RESOLVED_PATCH_ROOT/files/01-bore.patch"', result)\n            self.assertIn('BORE_PORT_VERSION="6.8.0"', result)\n            self.assertIn(str(record["sha256"]), result)\n            self.assertIn(str(sched_ext_record["sha256"]), result)\n            self.assertIn('files/01-bore-sched-ext-coexistence-fix-linux7.1.5-port.patch', result)\n            self.assertNotIn("6.8.0-rc1", result)\n            self.assertNotIn("7.1.4-sched-ext", result)\n\n'''
    path.write_text(text[:start] + new + text[end:], encoding="utf-8")


def delete_obsolete() -> None:
    for rel in (
        "patches/bore/7.1.4-bore-6.8.0-rc1.patch",
        "patches/bore/7.1.4-sched-ext-coexistence-fix.patch",
        ".github/workflows/update-marie-fallback.yml",
    ):
        (ROOT / rel).unlink(missing_ok=True)


def main() -> None:
    neutralize_reflex()
    neutralize_vram()
    neutralize_core()
    generic_sched_ext_template()
    modernize_finalizer_tests()
    delete_obsolete()


if __name__ == "__main__":
    main()
