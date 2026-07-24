#!/usr/bin/env python3
"""Adapt the upstream Zen profile to TurboDecky's non-conflicting policies."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PROJECT_OWNED_PATHS = {"block/elevator.c"}
BASE_SLICE_TOKEN = "sysctl_sched_base_slice"
MIGRATION_SECTION = """diff --git a/kernel/sched/fair.c b/kernel/sched/fair.c
--- a/kernel/sched/fair.c
+++ b/kernel/sched/fair.c
@@ -84,3 +84,7 @@
-__read_mostly unsigned int sysctl_sched_migration_cost\t= 500000UL;
+#ifdef CONFIG_ZEN_INTERACTIVE
+__read_mostly unsigned int sysctl_sched_migration_cost\t= 300000UL;
+#else
+__read_mostly unsigned int sysctl_sched_migration_cost\t= 500000UL;
+#endif
 
 static int __init setup_sched_thermal_decay_shift(char *str)
"""


class PortError(RuntimeError):
    pass


def split_sections(diff: str) -> list[str]:
    return [
        part
        for part in re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
        if part
    ]


def split_hunks(section: str) -> tuple[str, list[str]]:
    first = re.search(r"^@@ ", section, flags=re.MULTILINE)
    if first is None:
        return section, []
    header = section[: first.start()]
    hunks = [
        hunk
        for hunk in re.split(
            r"(?=^@@ )", section[first.start() :], flags=re.MULTILINE
        )
        if hunk
    ]
    return header, hunks


def section_path(header: str) -> str:
    match = re.match(r"diff --git a/(.+?) b/", header)
    if match is None:
        raise PortError("unable to parse unified-diff path")
    return match.group(1)


def sanitize_kconfig_help(hunk: str) -> str:
    replacements = {
        "Default scheduler for SQ": (
            "\t    Default scheduler for SQ..: project policy unchanged"
        ),
        "Default scheduler for MQ": (
            "\t    Default scheduler for MQ..: project policy unchanged"
        ),
        "Minimal granularity": (
            "\t    Minimal granularity............: project policy unchanged"
        ),
    }
    lines: list[str] = []
    for line in hunk.splitlines(keepends=True):
        replacement = next(
            (value for token, value in replacements.items() if token in line),
            None,
        )
        if replacement is None:
            lines.append(line)
            continue
        prefix = line[:1] if line[:1] in {"+", "-", " "} else ""
        ending = "\n" if line.endswith("\n") else ""
        lines.append(prefix + replacement + ending)
    return "".join(lines)


def prepare_patch(text: str) -> tuple[str, list[str]]:
    output: list[str] = []
    exclusions: list[str] = []
    migration_needed = False

    for section in split_sections(text):
        header, hunks = split_hunks(section)
        if not hunks:
            output.append(section)
            continue
        path = section_path(header)
        if path in PROJECT_OWNED_PATHS:
            exclusions.append(f"{path}: ADIOS project policy preserved")
            continue

        selected: list[str] = []
        for hunk in hunks:
            if path == "kernel/sched/fair.c" and BASE_SLICE_TOKEN in hunk:
                migration_needed = "sysctl_sched_migration_cost" in hunk
                exclusions.append(
                    "kernel/sched/fair.c: BORE base slice preserved; "
                    "migration cost ported separately"
                )
                continue
            if path == "init/Kconfig":
                hunk = sanitize_kconfig_help(hunk)
            selected.append(hunk)

        if selected:
            output.append(header + "".join(selected))

    if migration_needed:
        output.append(MIGRATION_SECTION)

    result = "".join(output)
    if "diff --git a/block/elevator.c b/block/elevator.c" in result:
        raise PortError("project-owned block/elevator.c remained in Zen patch")
    if result.count(BASE_SLICE_TOKEN):
        raise PortError("BORE-owned base slice remained in Zen patch")
    if "config ZEN_INTERACTIVE" not in result:
        raise PortError("Zen Kconfig definition was lost while adapting the patch")
    if migration_needed and result.count("sysctl_sched_migration_cost") != 3:
        raise PortError("migration-cost semantic port is malformed")
    return result, exclusions


def patch_files(text: str) -> list[str]:
    return sorted(
        {
            section_path(split_hunks(section)[0])
            for section in split_sections(text)
        }
    )


def patch_hunk_count(text: str) -> int:
    return sum(len(split_hunks(section)[1]) for section in split_sections(text))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    try:
        adapted, exclusions = prepare_patch(
            args.patch.read_text(encoding="utf-8")
        )
    except PortError as exc:
        raise SystemExit(f"Zen project-policy port failed: {exc}") from exc
    args.patch.write_text(adapted, encoding="utf-8")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("\n".join(exclusions) + "\n", encoding="utf-8")
    print(
        "Adapted Zen profile to preserve ADIOS and BORE policies: "
        + "; ".join(exclusions),
        flush=True,
    )


if __name__ == "__main__":
    main()
