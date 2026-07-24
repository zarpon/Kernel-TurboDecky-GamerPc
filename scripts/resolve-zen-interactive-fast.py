#!/usr/bin/env python3
"""Run the Zen profile resolver with bounded discovery and project policy."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("resolve-zen-interactive.py")
SPEC = importlib.util.spec_from_file_location(
    "resolve_zen_interactive_base", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise SystemExit(f"Unable to load Zen resolver from {MODULE_PATH}")
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)

PORT_PATH = Path(__file__).with_name("port-zen-interactive.py")
PORT_SPEC = importlib.util.spec_from_file_location("port_zen_interactive", PORT_PATH)
if PORT_SPEC is None or PORT_SPEC.loader is None:
    raise SystemExit(f"Unable to load Zen project port from {PORT_PATH}")
port = importlib.util.module_from_spec(PORT_SPEC)
PORT_SPEC.loader.exec_module(port)


def discover_symbol_files(checkout: Path, *, intro: str, head: str) -> list[str]:
    """Find only paths whose history actually changes the Zen symbol."""
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
        raise resolver.ResolveError(
            "official profile history contains no symbol-bearing files"
        )

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
        raise resolver.ResolveError(
            "current official profile no longer defines ZEN_INTERACTIVE"
        )
    if len(selected) < 2:
        raise resolver.ResolveError(
            "official profile resolves to too few symbol-bearing files"
        )
    return sorted(set(selected))


def option_path(name: str) -> Path:
    try:
        index = sys.argv.index(name)
        value = sys.argv[index + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"Missing required resolver argument {name}") from exc
    return Path(value)


def apply_project_policy() -> None:
    patch_path = option_path("--output")
    provenance_path = option_path("--provenance")
    lock_path = option_path("--lock")

    try:
        adapted, exclusions = port.prepare_patch(
            patch_path.read_text(encoding="utf-8")
        )
    except port.PortError as exc:
        raise SystemExit(f"Zen project-policy port failed: {exc}") from exc

    patch_path.write_text(adapted, encoding="utf-8")
    digest = hashlib.sha256(patch_path.read_bytes()).hexdigest()

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    component = lock["components"]["zen_interactive"]
    component.update(
        {
            "files": port.patch_files(adapted),
            "hunks": port.patch_hunk_count(adapted),
            "policy_exclusions": exclusions,
            "io_scheduler_policy": "ADIOS-preserved",
            "base_slice_policy": "BORE-preserved",
            "migration_cost_ns": 300000,
            "sha256": digest,
            "size": len(patch_path.read_bytes()),
        }
    )
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with provenance_path.open("a", encoding="utf-8") as provenance:
        provenance.write("Project policy: ADIOS default preserved\n")
        provenance.write("Project policy: BORE base slice preserved\n")
        provenance.write("Zen migration cost: 300000 ns\n")
        provenance.write(f"Adapted files: {', '.join(port.patch_files(adapted))}\n")
        provenance.write(f"Adapted hunks: {port.patch_hunk_count(adapted)}\n")
        provenance.write(f"Adapted SHA256: {digest}\n")
        for exclusion in exclusions:
            provenance.write(f"Policy exclusion: {exclusion}\n")

    print(
        "Adapted Zen profile to preserve project policies: "
        + "; ".join(exclusions),
        flush=True,
    )


resolver.discover_symbol_files = discover_symbol_files
resolver.main()
apply_project_policy()
