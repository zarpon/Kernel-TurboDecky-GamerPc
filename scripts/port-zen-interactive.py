#!/usr/bin/env python3
"""Adapt the upstream Zen profile to TurboDecky's non-conflicting policies."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

PROJECT_OWNED_PATHS = {"block/elevator.c"}
SEMANTIC_PORT_PATHS = {"mm/swap.c", "mm/swap_state.c"}
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
SWAP_SETUP_SECTION_LEGACY = """diff --git a/mm/swap.c b/mm/swap.c
--- a/mm/swap.c
+++ b/mm/swap.c
@@ -1098,15 +1098,20 @@ void __init swap_setup(void)
 {
+#ifdef CONFIG_ZEN_INTERACTIVE
+\t/* Only swap-in pages requested, avoid readahead */
+\tpage_cluster = 0;
+#else
 \tunsigned long megs = PAGES_TO_MB(totalram_pages());
 
 \t/* Use a smaller cluster for small-memory machines */
 \tif (megs < 16)
 \t\tpage_cluster = 2;
 \telse
 \t\tpage_cluster = 3;
 \t/*
 \t * Right now other parts of the system means that we
 \t * _really_ don't want to cluster much more
 \t */
+#endif
 
 \tregister_sysctl_init("vm", swap_sysctl_table);
 }
"""
SWAP_SETUP_SECTION_73 = """diff --git a/mm/swap_state.c b/mm/swap_state.c
--- a/mm/swap_state.c
+++ b/mm/swap_state.c
@@ -1014,15 +1014,20 @@ static void __init swap_readahead_setup(void)
 {
+#ifdef CONFIG_ZEN_INTERACTIVE
+\t/* Only swap-in pages requested, avoid readahead */
+\tpage_cluster = 0;
+#else
 \tunsigned long megs = PAGES_TO_MB(totalram_pages());
 
 \t/* Use a smaller cluster for small-memory machines */
 \tif (megs < 16)
 \t\tpage_cluster = 2;
 \telse
 \t\tpage_cluster = 3;
 \t/*
 \t * Right now other parts of the system means that we
 \t * _really_ don't want to cluster much more
 \t */
+#endif
 
 \tregister_sysctl_init("vm", swap_readahead_sysctl_table);
 }
"""


class PortError(RuntimeError):
    pass


def split_sections(diff: str) -> list[str]:
    return [part for part in re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE) if part]


def split_hunks(section: str) -> tuple[str, list[str]]:
    first = re.search(r"^@@ ", section, flags=re.MULTILINE)
    if first is None:
        return section, []
    header = section[: first.start()]
    hunks = [hunk for hunk in re.split(r"(?=^@@ )", section[first.start() :], flags=re.MULTILINE) if hunk]
    return header, hunks


def section_path(header: str) -> str:
    match = re.match(r"diff --git a/(.+?) b/", header)
    if match is None:
        raise PortError("unable to parse unified-diff path")
    return match.group(1)


def kernel_series_key() -> tuple[int, int]:
    raw = os.environ.get("KERNEL_SERIES", "0.0")
    match = re.fullmatch(r"(\d+)\.(\d+)", raw)
    if match is None:
        raise PortError(f"invalid KERNEL_SERIES for Zen semantic port: {raw!r}")
    return int(match.group(1)), int(match.group(2))


def swap_setup_section() -> tuple[str, str]:
    if kernel_series_key() >= (7, 3):
        return SWAP_SETUP_SECTION_73, "mm/swap_state.c"
    return SWAP_SETUP_SECTION_LEGACY, "mm/swap.c"


def sanitize_kconfig_help(hunk: str) -> str:
    replacements = {
        "Default scheduler for SQ": "\t    Default scheduler for SQ..: project policy unchanged",
        "Default scheduler for MQ": "\t    Default scheduler for MQ..: project policy unchanged",
        "Minimal granularity": "\t    Minimal granularity............: project policy unchanged",
    }
    lines: list[str] = []
    for line in hunk.splitlines(keepends=True):
        replacement = next((value for token, value in replacements.items() if token in line), None)
        if replacement is None:
            lines.append(line)
            continue
        prefix = line[:1] if line[:1] in {"+", "-", " "} else ""
        ending = "\n" if line.endswith("\n") else ""
        lines.append(prefix + replacement + ending)
    return "".join(lines)


def assert_added_conditionals_balanced(text: str, *, paths: set[str] | None = None) -> None:
    opening = re.compile(r"^\s*#\s*(?:if|ifdef|ifndef)\b")
    closing = re.compile(r"^\s*#\s*endif\b")
    for section in split_sections(text):
        header, _ = split_hunks(section)
        path = section_path(header)
        if paths is not None and path not in paths:
            continue
        depth = 0
        for raw_line in section.splitlines():
            if raw_line.startswith(("+++", "---")):
                continue
            if raw_line[:1] not in {"+", " "}:
                continue
            line = raw_line[1:]
            if opening.match(line):
                depth += 1
            elif closing.match(line):
                depth -= 1
                if depth < 0:
                    raise PortError(f"{path}: preprocessor group closes without an opener")
        if depth:
            raise PortError(f"{path}: preprocessor group is unterminated ({depth} open)")


def prepare_patch(text: str) -> tuple[str, list[str]]:
    output: list[str] = []
    exclusions: list[str] = []
    migration_needed = False
    swap_setup_needed = False

    for section in split_sections(text):
        header, hunks = split_hunks(section)
        if not hunks:
            output.append(section)
            continue
        path = section_path(header)
        if path in PROJECT_OWNED_PATHS:
            exclusions.append(f"{path}: ADIOS project policy preserved")
            continue
        if path == "mm/swap.c":
            swap_setup_needed = True
            exclusions.append("mm/swap.c: page-cluster tuning ported semantically to the target kernel layout")
            continue

        selected: list[str] = []
        for hunk in hunks:
            if path == "kernel/sched/fair.c" and BASE_SLICE_TOKEN in hunk:
                migration_needed = "sysctl_sched_migration_cost" in hunk
                exclusions.append("kernel/sched/fair.c: BORE base slice preserved; migration cost ported separately")
                continue
            if path == "init/Kconfig":
                hunk = sanitize_kconfig_help(hunk)
            selected.append(hunk)
        if selected:
            output.append(header + "".join(selected))

    if migration_needed:
        output.append(MIGRATION_SECTION)
    semantic_swap_path = ""
    if swap_setup_needed:
        section, semantic_swap_path = swap_setup_section()
        output.append(section)
        exclusions.append(f"Zen swap readahead policy applied at {semantic_swap_path}")

    result = "".join(output)
    if "diff --git a/block/elevator.c b/block/elevator.c" in result:
        raise PortError("project-owned block/elevator.c remained in Zen patch")
    if result.count(BASE_SLICE_TOKEN):
        raise PortError("BORE-owned base slice remained in Zen patch")
    if "config ZEN_INTERACTIVE" not in result:
        raise PortError("Zen Kconfig definition was lost while adapting the patch")
    if migration_needed and result.count("sysctl_sched_migration_cost") != 3:
        raise PortError("migration-cost semantic port is malformed")
    if swap_setup_needed:
        marker = f"diff --git a/{semantic_swap_path} b/{semantic_swap_path}"
        if result.count(marker) != 1:
            raise PortError("swap page-cluster semantic port is duplicated")
        if result.count("page_cluster = 0;") != 1:
            raise PortError("swap page-cluster semantic port is malformed")
    assert_added_conditionals_balanced(result, paths=SEMANTIC_PORT_PATHS)
    return result, exclusions


def patch_files(text: str) -> list[str]:
    return sorted({section_path(split_hunks(section)[0]) for section in split_sections(text)})


def patch_hunk_count(text: str) -> int:
    return sum(len(split_hunks(section)[1]) for section in split_sections(text))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    try:
        adapted, exclusions = prepare_patch(args.patch.read_text(encoding="utf-8"))
    except PortError as exc:
        raise SystemExit(f"Zen project-policy port failed: {exc}") from exc
    args.patch.write_text(adapted, encoding="utf-8")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("\n".join(exclusions) + "\n", encoding="utf-8")
    print("Adapted Zen profile to preserve ADIOS and BORE policies: " + "; ".join(exclusions), flush=True)


if __name__ == "__main__":
    main()
