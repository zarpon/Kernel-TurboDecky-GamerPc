#!/usr/bin/env python3
"""Validate the repository's fail-closed BORE source and Kconfig policy."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/patch-sources.json"
KERNEL_CONFIG = ROOT / "config/kernelnote.config"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    components = manifest.get("components")
    if not isinstance(components, dict):
        raise SystemExit("patch source manifest has no components mapping")

    removed_name = "infi" + "nity"
    if removed_name in components:
        raise SystemExit("removed scheduler component remains in patch manifest")

    bore = components.get("bore")
    if not isinstance(bore, dict):
        raise SystemExit("BORE component is missing from patch manifest")
    if bore.get("repo") != "https://github.com/firelzrd/bore-scheduler.git":
        raise SystemExit("unexpected BORE repository")
    if bore.get("ref") != "main":
        raise SystemExit("BORE must follow the developer's main branch")
    if bore.get("exact_globs") != ["patches/testing/*linux{series}*bore*.patch"]:
        raise SystemExit("BORE must resolve only exact-series testing patches")
    if bore.get("fallback_globs") != [] or bore.get("require_exact_series") is not True:
        raise SystemExit("BORE source policy must fail closed without series fallback")

    required = set(bore.get("required_markers", []))
    expected = {"SCHED_BORE_VERSION", "CONFIG_SCHED_BORE", "kernel/sched/bore.c"}
    if not expected.issubset(required):
        raise SystemExit("BORE semantic source markers are incomplete")

    config = KERNEL_CONFIG.read_text(encoding="utf-8")
    if "CONFIG_SCHED_BORE=y" not in config:
        raise SystemExit("CONFIG_SCHED_BORE is not built in")
    if "# CONFIG_SCHED_PDS is not set" not in config:
        raise SystemExit("PDS must remain disabled")
    if "# CONFIG_SCHED_BMQ is not set" not in config:
        raise SystemExit("BMQ must remain disabled")

    print("BORE source and Kconfig policy passed")


if __name__ == "__main__":
    main()
