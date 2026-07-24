#!/usr/bin/env python3
"""Run the Zen profile resolver with bounded symbol-file discovery."""
from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("resolve-zen-interactive.py")
SPEC = importlib.util.spec_from_file_location("resolve_zen_interactive_base", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit(f"Unable to load Zen resolver from {MODULE_PATH}")
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


def discover_symbol_files(checkout: Path, *, intro: str, head: str) -> list[str]:
    """Find only paths whose history actually adds or changes the Zen symbol.

    Unlike a tree-wide ``git grep`` in a blob-less clone, ``git log -G`` limits
    object materialization to commits whose patches mention ZEN_INTERACTIVE.
    The candidate set is then verified against current HEAD.
    """
    paths = resolver.run(
        [
            "git",
            "log",
            "--format=",
            "--name-only",
            "-G",
            resolver.SYMBOL,
            f"{intro}^..{head}",
            "--",
        ],
        cwd=checkout,
        timeout=resolver.FETCH_TIMEOUT,
    ).splitlines()

    candidates = sorted({path for path in paths if path.strip()})
    if not candidates:
        raise resolver.ResolveError("official profile history contains no symbol-bearing files")

    selected: list[str] = []
    for path in candidates:
        try:
            content = resolver.read_file_at(checkout, head, path)
        except resolver.ResolveError as exc:
            if "does not exist" in str(exc):
                continue
            raise
        if resolver.SYMBOL in content:
            selected.append(path)

    if "init/Kconfig" not in selected:
        raise resolver.ResolveError("current official profile no longer defines ZEN_INTERACTIVE")
    if len(selected) < 2:
        raise resolver.ResolveError("official profile resolves to too few symbol-bearing files")
    return sorted(set(selected))


resolver.discover_symbol_files = discover_symbol_files
resolver.main()
