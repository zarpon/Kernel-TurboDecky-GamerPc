#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = "__DYNAMIC_PATCH_LOCK_REQUIRED__"
LATEST = "__LATEST_UPSTREAM_LINUX_REQUIRED__"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def set_assignment(text: str, variable: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(variable)}=.*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(f"{variable}: assignment count={len(matches)}")
    return pattern.sub(f'{variable}="{value}"', text, count=1)


def clean_core() -> None:
    path = ROOT / "scripts/build-kernelnote-core.sh"
    text = path.read_text(encoding="utf-8")
    assignments = {
        "KERNEL_TAG": LATEST,
        "BORE_REPO": LOCK,
        "BORE_COMMIT": LOCK,
        "BORE_PATCH_PATH": LOCK,
        "BORE_PATCH": "$PATCHDIR/01-bore-current-port.patch",
        "BORE_PORT_VERSION": LOCK,
        "BORE_PORT_UPSTREAM_SHA256": LOCK,
        "BORE_SCHED_EXT_REPO": LOCK,
        "BORE_SCHED_EXT_COMMIT": LOCK,
        "BORE_SCHED_EXT_PATCH_PATH": LOCK,
        "BORE_SCHED_EXT_PATCH": "$PATCHDIR/01-bore-sched-ext-current-port.patch",
        "BORE_SCHED_EXT_PORT_UPSTREAM_SHA256": LOCK,
        "MARIE_REPO": LOCK,
        "MARIE_COMMIT": LOCK,
        "MARIE_PATCH_PATH": LOCK,
        "PATCH_MARIE_VERSION": LOCK,
    }
    for variable, value in assignments.items():
        text = set_assignment(text, variable, value)
    path.write_text(text, encoding="utf-8")


def clean_upstream_rewriter() -> None:
    path = ROOT / "scripts/apply-upstream-generic.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "'KERNEL_TAG=\"v7.1.4\"\\n'",
        "'KERNEL_TAG=\"__LATEST_UPSTREAM_LINUX_REQUIRED__\"\\n'",
        "dynamic kernel tag sentinel",
    )
    path.write_text(text, encoding="utf-8")


def clean_wrapper() -> None:
    path = ROOT / "scripts/build-kernelnote.sh"
    text = path.read_text(encoding="utf-8")
    assignments = {
        "ZRAM_IR_REPO": LOCK,
        "ZRAM_IR_COMMIT": LOCK,
        "ZRAM_IR_PATCH_PATH": LOCK,
        "ZRAM_IR_PATCH": "$PATCHDIR/0004-zram-ir-current.patch",
        "POC_REPO": LOCK,
        "POC_COMMIT": LOCK,
        "POC_PATCH_PATH": LOCK,
        "POC_PATCH": "$PATCHDIR/0005-poc-selector-current.patch",
        "NAP_REPO": LOCK,
        "NAP_COMMIT": LOCK,
        "NAP_PATCH_PATH": LOCK,
        "NAP_PATCH": "$PATCHDIR/0006-nap-current-port.patch",
    }
    for variable, value in assignments.items():
        text = set_assignment(text, variable, value)

    nap_anchor = 'NAP_PATCH="$PATCHDIR/0006-nap-current-port.patch"\n'
    if text.count("PATCH_ZRAM_IR_VERSION=") == 0:
        text = replace_once(
            text,
            nap_anchor,
            nap_anchor
            + f'PATCH_ZRAM_IR_VERSION="{LOCK}"\n'
            + f'PATCH_POC_VERSION="{LOCK}"\n'
            + f'PATCH_NAP_VERSION="{LOCK}"\n',
            "dynamic project version sentinels",
        )

    replacements = {
        '"ZRAM-IR 1.2 for Linux 7.1"': '"ZRAM-IR $PATCH_ZRAM_IR_VERSION current upstream source"',
        "'Subject: [PATCH] linux7.1-rc1-zram-ir-1.2'": "'zram-ir'",
        '"POC Selector 2.6.2r2 for Linux 7.1"': '"POC Selector $PATCH_POC_VERSION current upstream source"',
        "'Subject: [PATCH] 7.1-rc1-poc-selector-v2.6.2r2'": "'poc-selector'",
        '"NAP 0.5.0 stable port source"': '"NAP $PATCH_NAP_VERSION current upstream port source"',
        "'Subject: [PATCH] 6.18.3-nap-v0.5.0'": "'nap'",
        'echo "==> Applying ZRAM Immediate Recompression 1.2 for Linux 7.1"': 'echo "==> Applying ZRAM Immediate Recompression $PATCH_ZRAM_IR_VERSION for Linux $KERNEL_VERSION"',
        "grep -Fq '#define ZRAM_IR_VERSION \\\"1.2\\\"' drivers/block/zram/zram_drv.c": 'grep -Fq "$PATCH_ZRAM_IR_VERSION" drivers/block/zram/zram_drv.c',
        'echo "==> ZRAM-IR 1.2 patch applied successfully"': 'echo "==> ZRAM-IR $PATCH_ZRAM_IR_VERSION patch applied successfully"',
        'echo "==> Applying native Linux 7.1 POC Selector 2.6.2r2"': 'echo "==> Applying POC Selector $PATCH_POC_VERSION to Linux $KERNEL_VERSION"',
        'echo "==> POC Selector 2.6.2r2 applied successfully"': 'echo "==> POC Selector $PATCH_POC_VERSION applied successfully"',
        'echo "==> Porting NAP 0.5.0 from Linux 6.18.3 to the target Linux series"': 'echo "==> Porting current upstream NAP $PATCH_NAP_VERSION to Linux $KERNEL_VERSION"',
        "grep -Fq '#define CPUIDLE_NAP_VERSION  \\\"0.5.0\\\"' \\\n    drivers/cpuidle/governors/nap/nap.c": 'grep -Fq "$PATCH_NAP_VERSION" \\\n    drivers/cpuidle/governors/nap/nap.c',
        'echo "==> NAP 0.5.0 Linux 7.1 port applied successfully"': 'echo "==> NAP $PATCH_NAP_VERSION port applied successfully"',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            raise SystemExit(f"wrapper stale-version anchor missing: {old[:80]}")
    path.write_text(text, encoding="utf-8")


def clean_requested_series() -> None:
    path = ROOT / "scripts/apply-requested-patch-series.py"
    text = path.read_text(encoding="utf-8")
    requested = {
        "c23_libbpf": ("08-c23-libbpf.patch", "08-c23-libbpf"),
        "clear": ("09-clear.patch", "09-clear"),
        "fsync": ("10-fsync-futex-waitv.patch", "10-fsync"),
        "o3": ("11-o3.patch", "11-o3"),
        "bt_ssp": ("12-bt-ssp-key-size.patch", "12-bt-ssp"),
        "libbpf_uninitialized": ("13-libbpf-uninitialized.patch", "13-libbpf-uninitialized"),
        "cpu_optimizations": ("14-cpu-optimizations.patch", "14-cpu-optimizations"),
        "dkms_clang": ("15-dkms-clang.patch", "15-dkms-clang"),
        "clang_polly": ("16-clang-polly.patch", "16-clang-polly"),
        "firmware_name": ("17-firmware-name.patch", "17-firmware-name"),
        "minstrel_frac": ("18-minstrel-frac.patch", "18-minstrel-frac"),
        "minstrel_fluctuation": ("19-minstrel-fluctuation.patch", "19-minstrel-fluctuation"),
        "minstrel_downgrade": ("20-minstrel-downgrade.patch", "20-minstrel-downgrade"),
        "ath11k_remapped_ce": ("21-ath11k-remapped-ce.patch", "21-ath11k-remapped-ce"),
        "ath11k_disable_key": ("22-ath11k-disable-key.patch", "22-ath11k-disable-key"),
        "ath11k_upstream": ("23-ath11k-upstream.patch", "23-ath11k-upstream"),
    }
    for name, (output, prefix) in requested.items():
        sentinel = f'"{LOCK}:{name}"'
        if sentinel in text:
            continue
        header = rf'(fetch_candidate_patch [^\n]+ \\\n    "\$REQUESTED_SERIES_DIR/{re.escape(output)}" "{re.escape(prefix)}" \\\n)'
        pattern = re.compile(header + r'.*?(?=\n\n  fetch_candidate_patch|\n\n\})', re.S)
        match = pattern.search(text)
        if not match:
            raise SystemExit(f"requested patch block missing: {name}")
        text = text[:match.start()] + match.group(1) + f'    {sentinel}' + text[match.end():]
    path.write_text(text, encoding="utf-8")


def clean_dynamic_rewriter() -> None:
    path = ROOT / "scripts/apply-dynamic-patch-sources.py"
    text = path.read_text(encoding="utf-8")
    old = '''def project_version(record: dict[str, Any], fallback: str) -> str:\n    value = record.get("project_version")\n    return str(value) if value else fallback\n'''
    new = '''def project_version(record: dict[str, Any], label: str) -> str:\n    value = record.get("project_version")\n    if not value:\n        raise RewriteError(f"locked project version is missing for {label}")\n    return str(value)\n'''
    if old in text:
        text = replace_once(text, old, new, "strict project version")

    for name in ("marie", "reflex", "zram_ir", "poc", "nap"):
        text = text.replace(
            f'project_version(component(lock, "{name}"), "unknown")',
            f'project_version(component(lock, "{name}"), "{name}")',
        )

    old_requested = '''    for name, (output, prefix) in REQUESTED.items():\n        component(lock, name)\n        anchor = f'"$REQUESTED_SERIES_DIR/{output}" "{prefix}" \\\\\\n'\n        replacement = anchor + f'    "file://$RESOLVED_PATCH_ROOT/files/{output}" \\\\\\n'\n        text = replace_once(text, anchor, replacement, f"local candidate {name}")\n'''
    new_requested = '''    for name, (output, _prefix) in REQUESTED.items():\n        component(lock, name)\n        sentinel = f'"__DYNAMIC_PATCH_LOCK_REQUIRED__:{name}"'\n        text = replace_once(\n            text, sentinel, f'"file://$RESOLVED_PATCH_ROOT/files/{output}"',\n            f"locked candidate {name}",\n        )\n'''
    if old_requested in text:
        text = replace_once(text, old_requested, new_requested, "requested lock-only source rewrite")

    old_versions = '''    anchor = 'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"\\n'\n    position = text.find(anchor)\n    if position < 0:\n        raise RewriteError("dynamic wrapper versions: NAP patch assignment is missing")\n    insertion = (\n        f'PATCH_ZRAM_IR_VERSION="{versions["zram_ir"]}"\\n'\n        + f'PATCH_POC_VERSION="{versions["poc"]}"\\n'\n        + f'PATCH_NAP_VERSION="{versions["nap"]}"\\n'\n    )\n    position += len(anchor)\n    text = text[:position] + insertion + text[position:]\n'''
    new_versions = '''    text = replace_assignment(text, "PATCH_ZRAM_IR_VERSION", versions["zram_ir"])\n    text = replace_assignment(text, "PATCH_POC_VERSION", versions["poc"])\n    text = replace_assignment(text, "PATCH_NAP_VERSION", versions["nap"])\n'''
    if old_versions in text:
        text = replace_once(text, old_versions, new_versions, "wrapper version sentinels")

    stale = (
        '        "grep -Fq \'#define ZRAM_IR_VERSION \\\"1.2\\\"\' drivers/block/zram/zram_drv.c":\n            \'[[ "$PATCH_ZRAM_IR_VERSION" == "unknown" ]] || grep -Fq "$PATCH_ZRAM_IR_VERSION" drivers/block/zram/zram_drv.c\',\n',
        '        "grep -Fq \'#define CPUIDLE_NAP_VERSION  \\\"0.5.0\\\"\' \\\\\\n    drivers/cpuidle/governors/nap/nap.c":\n            \'[[ "$PATCH_NAP_VERSION" == "unknown" ]] || grep -Fq "$PATCH_NAP_VERSION" \\\\\\n    drivers/cpuidle/governors/nap/nap.c\',\n',
        '        "\'Subject: [PATCH] linux7.1-rc1-zram-ir-1.2\'": "\'zram-ir\'",\n',
        '        "\'Subject: [PATCH] 7.1-rc1-poc-selector-v2.6.2r2\'": "\'poc-selector\'",\n',
        '        "\'Subject: [PATCH] 6.18.3-nap-v0.5.0\'": "\'nap\'",\n',
    )
    for item in stale:
        text = text.replace(item, "")
    path.write_text(text, encoding="utf-8")


def clean_openwrt_fallbacks() -> None:
    path = ROOT / "scripts/apply-zarpon-generic-name.py"
    text = path.read_text(encoding="utf-8")
    marker = "    # Retain vendored OpenWrt copies only as emergency fallbacks."
    if marker in text:
        start = text.index(marker)
        end = text.index('\n    path.write_text(source, encoding="utf-8")', start)
        text = text[:start] + "    # Requested patch bytes are supplied exclusively by the authenticated dynamic lock.\n" + text[end:]
    path.write_text(text, encoding="utf-8")


def clean_config() -> None:
    path = ROOT / "config/kernelnote.config"
    text = path.read_text(encoding="utf-8")
    if "CONFIG_MULTIPLEXER=y" in text:
        text = text.replace(
            "# MULTIPLEXER is boolean in current kernels; never carry the stale module value.\nCONFIG_MULTIPLEXER=y",
            "# MULTIPLEXER is hidden; MUX_CORE is its public selector.\nCONFIG_MUX_CORE=y",
            1,
        )
    if "CONFIG_MUX_CORE=y" not in text:
        raise SystemExit("MUX_CORE configuration missing")
    path.write_text(text, encoding="utf-8")


def clean_validation() -> None:
    path = ROOT / "scripts/validate-dynamic-patches-local.sh"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "grep -Fq '7.1.4-sched-ext-coexistence-fix.patch' \"$ROOT/scripts/build-kernelnote-core.sh\"\n",
        "grep -Fq '__DYNAMIC_PATCH_LOCK_REQUIRED__' \"$ROOT/scripts/build-kernelnote-core.sh\"\n",
        1,
    )
    marker = "grep -Fq 'patch-lock.json' \"$ROOT/scripts/apply-dynamic-patch-sources.py\"\n"
    if "locked project version is missing" not in text:
        guard = marker + \
            "grep -Fq '__LATEST_UPSTREAM_LINUX_REQUIRED__' \"$ROOT/scripts/build-kernelnote-core.sh\"\n" + \
            "grep -Fq '__DYNAMIC_PATCH_LOCK_REQUIRED__' \"$ROOT/scripts/build-kernelnote.sh\"\n" + \
            "! grep -Fq 'zram-ir-1.2' \"$ROOT/scripts/build-kernelnote.sh\"\n" + \
            "! grep -Fq 'poc-selector-v2.6.2r2' \"$ROOT/scripts/build-kernelnote.sh\"\n" + \
            "! grep -Fq '6.18.3-nap-v0.5.0' \"$ROOT/scripts/build-kernelnote.sh\"\n" + \
            "! grep -Fq 'emergency fallbacks' \"$ROOT/scripts/apply-zarpon-generic-name.py\"\n" + \
            "! grep -Eq 'https?://' \"$ROOT/scripts/apply-requested-patch-series.py\"\n" + \
            "grep -Fq 'locked project version is missing' \"$ROOT/scripts/apply-dynamic-patch-sources.py\"\n"
        text = replace_once(text, marker, guard, "upstream-only validation guards")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    clean_core()
    clean_upstream_rewriter()
    clean_wrapper()
    clean_requested_series()
    clean_dynamic_rewriter()
    clean_openwrt_fallbacks()
    clean_config()
    clean_validation()


if __name__ == "__main__":
    main()
