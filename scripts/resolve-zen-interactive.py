#!/usr/bin/env python3
"""Materialize the current official CONFIG_ZEN_INTERACTIVE profile.

Zen has not published a 7.1 zen-sauce branch yet. The resolver follows the
current 7.0/zen-sauce HEAD, finds the commit that introduced the profile and
retains only unified-diff hunks explicitly gated by ZEN_INTERACTIVE. THP and
transparent-hugepage changes are deliberately excluded so the existing kernel
THP policy remains untouched.
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
THP_PATHS = {"mm/huge_memory.c"}
THP_TOKENS = re.compile(
    r"TRANSPARENT_HUGEPAGE|khugepaged|\bTHP(?:_|\b)|transparent[ -]hugepage",
    re.IGNORECASE,
)


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


def sanitize_init_kconfig(hunk: str) -> str:
    # The upstream help text advertises a THP default change that is intentionally
    # excluded here. Keep the option definition, but make the documentation match
    # the resulting behavior.
    lines = []
    for line in hunk.splitlines(keepends=True):
        if "Background-reclaim hugepages" in line:
            prefix = line[:1] if line[:1] in {"+", "-", " "} else ""
            ending = "\n" if line.endswith("\n") else ""
            lines.append(prefix + "\t    Transparent hugepage policy.......: unchanged" + ending)
        else:
            lines.append(line)
    return "".join(lines)


def hunk_touches_thp(path: str, hunk: str) -> bool:
    if path in THP_PATHS:
        return True
    if path == "init/Kconfig":
        # Keep the defining Kconfig hunk; its THP help line is sanitized above.
        return False
    return bool(THP_TOKENS.search(hunk))


def assert_thp_untouched(patch: str) -> None:
    if "diff --git a/mm/huge_memory.c b/mm/huge_memory.c" in patch:
        raise ResolveError("Zen profile unexpectedly modifies mm/huge_memory.c")
    for line in patch.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        if THP_TOKENS.search(line):
            raise ResolveError(f"Zen profile unexpectedly changes THP content: {line}")


def filter_symbol_hunks(diff: str) -> tuple[str, list[str], int, int]:
    output: list[str] = []
    files: list[str] = []
    kept_hunks = 0
    excluded_thp_hunks = 0

    for section in split_sections(diff):
        first_hunk = re.search(r"^@@ ", section, flags=re.MULTILINE)
        if not first_hunk:
            continue
        header = section[: first_hunk.start()]
        match = re.match(r"diff --git a/(.+?) b/", header)
        if not match:
            raise ResolveError("unable to parse diff filename")
        path = match.group(1)

        hunks = [
            hunk
            for hunk in re.split(r"(?=^@@ )", section[first_hunk.start() :], flags=re.MULTILINE)
            if hunk
        ]
        selected: list[str] = []
        for hunk in hunks:
            if SYMBOL not in hunk:
                continue
            if hunk_touches_thp(path, hunk):
                excluded_thp_hunks += 1
                continue
            if path == "init/Kconfig":
                hunk = sanitize_init_kconfig(hunk)
            selected.append(hunk)

        if not selected:
            continue
        files.append(path)
        kept_hunks += len(selected)
        output.append(header + "".join(selected))

    result = "".join(output)
    if "config ZEN_INTERACTIVE" not in result:
        raise ResolveError("official profile patch does not define config ZEN_INTERACTIVE")
    if result.count(SYMBOL) < 2:
        raise ResolveError("official profile contains too few ZEN_INTERACTIVE references")
    assert_thp_untouched(result)
    return result, files, kept_hunks, excluded_thp_hunks


def fetch_profile(checkout: Path) -> tuple[str, str, str, str, list[str], int, int]:
    shutil.rmtree(checkout, ignore_errors=True)
    checkout.mkdir(parents=True)
    run(["git", "init", "--quiet"], cwd=checkout)
    run(["git", "remote", "add", "origin", REPO], cwd=checkout)
    run(["git", "config", "remote.origin.promisor", "true"], cwd=checkout)
    run(["git", "config", "remote.origin.partialclonefilter", "blob:none"], cwd=checkout)

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
    symbol_files = run(["git", "grep", "-l", SYMBOL, head, "--"], cwd=checkout).splitlines()
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
    patch, selected_files, hunks, excluded = filter_symbol_hunks(full_diff)
    return patch, head, intro, base, selected_files, hunks, excluded


def update_lock(
    path: Path,
    *,
    output: Path,
    head: str,
    intro: str,
    base: str,
    files: list[str],
    hunks: int,
    excluded_thp_hunks: int,
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
        "excluded_thp_hunks": excluded_thp_hunks,
        "thp_policy": "preserved-unchanged",
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
        patch, head, intro, base, files, hunks, excluded = fetch_profile(args.checkout)
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
                "THP policy: preserved unchanged; all THP hunks excluded",
                f"Excluded THP hunks: {excluded}",
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
        excluded_thp_hunks=excluded,
    )
    print(
        f"Resolved official Zen interactive profile {head}: {hunks} hunks in "
        f"{len(files)} files; excluded {excluded} THP hunks"
    )


if __name__ == "__main__":
    main()
