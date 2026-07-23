#!/usr/bin/env python3
"""Materialize the current official CONFIG_ZEN_INTERACTIVE profile.

Zen has not published a 7.1 zen-sauce branch yet.  The resolver follows the
current 7.0/zen-sauce HEAD, finds the commit that introduced the profile and
retains only unified-diff hunks that are explicitly gated by
ZEN_INTERACTIVE.  The resulting small patch is then ported by the build to the
current stable Linux tree.  Any upstream layout change fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

REPO = "https://github.com/zen-kernel/zen-kernel.git"
REF = "7.0/zen-sauce"
KERNEL_TARGET = "7.0"
SYMBOL = "ZEN_INTERACTIVE"


class ResolveError(RuntimeError):
    pass


def run(args: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise ResolveError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed.stdout


def split_sections(diff: str) -> list[str]:
    return [part for part in re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE) if part]


def filter_symbol_hunks(diff: str) -> tuple[str, list[str], int]:
    output: list[str] = []
    files: list[str] = []
    kept_hunks = 0

    for section in split_sections(diff):
        first_hunk = re.search(r"^@@ ", section, flags=re.MULTILINE)
        if not first_hunk:
            continue
        header = section[: first_hunk.start()]
        hunks = [
            hunk
            for hunk in re.split(r"(?=^@@ )", section[first_hunk.start() :], flags=re.MULTILINE)
            if hunk
        ]
        selected = [hunk for hunk in hunks if SYMBOL in hunk]
        if not selected:
            continue

        match = re.match(r"diff --git a/(.+?) b/", header)
        if not match:
            raise ResolveError("unable to parse diff filename")
        files.append(match.group(1))
        kept_hunks += len(selected)
        output.append(header + "".join(selected))

    result = "".join(output)
    if "config ZEN_INTERACTIVE" not in result:
        raise ResolveError("official profile patch does not define config ZEN_INTERACTIVE")
    if result.count(SYMBOL) < 2:
        raise ResolveError("official profile contains too few ZEN_INTERACTIVE references")
    return result, files, kept_hunks


def fetch_profile(checkout: Path) -> tuple[str, str, str, str, list[str], int]:
    shutil.rmtree(checkout, ignore_errors=True)
    checkout.mkdir(parents=True)
    run(["git", "init", "--quiet"], cwd=checkout)
    run(["git", "remote", "add", "origin", REPO], cwd=checkout)
    run(["git", "config", "remote.origin.promisor", "true"], cwd=checkout)
    run(["git", "config", "remote.origin.partialclonefilter", "blob:none"], cwd=checkout)

    # The current sauce branch is short. Deepen automatically if the introducing
    # commit's parent is not available after the initial partial fetch.
    depth = 128
    intro = ""
    while depth <= 2048:
        run(
            [
                "git",
                "fetch",
                "--force",
                "--no-tags",
                f"--depth={depth}",
                "--filter=blob:none",
                "origin",
                f"refs/heads/{REF}",
            ],
            cwd=checkout,
        )
        candidates = run(
            [
                "git",
                "log",
                "--reverse",
                "--format=%H",
                "-S",
                "config ZEN_INTERACTIVE",
                "FETCH_HEAD",
                "--",
                "init/Kconfig",
            ],
            cwd=checkout,
        ).splitlines()
        if candidates:
            intro = candidates[0]
            parent_check = subprocess.run(
                ["git", "cat-file", "-e", f"{intro}^{{commit}}"],
                cwd=checkout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if parent_check.returncode == 0:
                break
        depth *= 2
    else:
        raise ResolveError("could not locate the complete ZEN_INTERACTIVE introduction history")

    head = run(["git", "rev-parse", "FETCH_HEAD"], cwd=checkout).strip()
    base = run(["git", "rev-parse", f"{intro}^"], cwd=checkout).strip()
    symbol_files = run(
        ["git", "grep", "-l", SYMBOL, head, "--"], cwd=checkout
    ).splitlines()
    if not symbol_files:
        raise ResolveError("official branch contains no ZEN_INTERACTIVE users")

    full_diff = run(
        [
            "git",
            "diff",
            "--full-index",
            "--no-ext-diff",
            base,
            head,
            "--",
            *symbol_files,
        ],
        cwd=checkout,
    )
    patch, selected_files, hunks = filter_symbol_hunks(full_diff)
    return patch, head, intro, base, selected_files, hunks


def update_lock(
    path: Path,
    *,
    output: Path,
    head: str,
    intro: str,
    base: str,
    files: list[str],
    hunks: int,
) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    components = data.setdefault("components", {})
    content = output.read_bytes()
    components["zen_interactive"] = {
        "kind": "git_profile",
        "repo": REPO,
        "ref": REF,
        "commit": head,
        "base_commit": base,
        "introduction_commit": intro,
        "kernel_target": KERNEL_TARGET,
        "selection": "nearest-series-profile",
        "output": str(output),
        "files": files,
        "hunks": hunks,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()

    try:
        patch, head, intro, base, files, hunks = fetch_profile(args.checkout)
    except ResolveError as exc:
        raise SystemExit(f"Zen interactive resolver failed: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(patch, encoding="utf-8")
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.provenance.write_text(
        "\n".join(
            [
                "Component: Zen interactive tuning profile",
                f"Repository: {REPO}",
                f"Ref: {REF}",
                f"Commit: {head}",
                f"Introduction commit: {intro}",
                f"Diff base: {base}",
                f"Kernel target: {KERNEL_TARGET}",
                "Selection: nearest official series; symbol-gated hunks only",
                f"Files: {', '.join(files)}",
                f"Hunks: {hunks}",
                f"SHA256: {digest}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    update_lock(
        args.lock,
        output=args.output,
        head=head,
        intro=intro,
        base=base,
        files=files,
        hunks=hunks,
    )
    print(f"Resolved official Zen interactive profile {head}: {hunks} hunks in {len(files)} files")


if __name__ == "__main__":
    main()
