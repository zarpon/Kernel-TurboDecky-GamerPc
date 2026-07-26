#!/usr/bin/env python3
"""Materialize the current official CONFIG_ZEN_INTERACTIVE profile.

The resolver selects the newest official ``<kernel-series>/zen-sauce`` branch
compatible with the stable kernel selected for this build. It finds the commit
that introduced the profile, retains only unified-diff hunks explicitly gated
by ZEN_INTERACTIVE, and adds the current Zen compatibility commits that are not
part of that symbol-gated profile. THP and transparent-hugepage changes are
deliberately excluded so the existing kernel THP policy remains untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, NamedTuple

REPO = "https://github.com/zen-kernel/zen-kernel.git"
DEFAULT_KERNEL_SERIES = "7.1"
SERIES_RE = re.compile(r"^[0-9]+\.[0-9]+$")
ZEN_REF_RE = re.compile(r"^refs/heads/([0-9]+\.[0-9]+)/zen-sauce$")
SYMBOL = "ZEN_INTERACTIVE"
SYMBOL_DEFINITION = "config ZEN_INTERACTIVE"
INTRODUCTION_SUBJECT = "ZEN: INTERACTIVE: Base config item"
THP_PATHS = {"mm/huge_memory.c"}
THP_TOKENS = re.compile(
    r"TRANSPARENT_HUGEPAGE|khugepaged|\bTHP(?:_|\b)|transparent[ -]hugepage",
    re.IGNORECASE,
)
DEFAULT_COMMAND_TIMEOUT = 90
FETCH_TIMEOUT = 180
TOTAL_RESOLVE_TIMEOUT = 600
MAX_HISTORY_DEPTH = 2048
_RESOLVE_DEADLINE: float | None = None

COMPATIBILITY_SPECS = (
    {
        "name": "evdev-call-rcu",
        "path": "drivers/input/evdev.c",
        "pattern": "evdev_reclaim_client",
        "marker": "call_rcu(&client->rcu",
    },
    {
        "name": "cpufreq-pstate-schedutil-dependency",
        "path": "drivers/cpufreq/Kconfig.x86",
        "pattern": "select CPU_FREQ_GOV_SCHEDUTIL",
        "marker": "CPU_FREQ_GOV_SCHEDUTIL",
    },
)


class ResolveError(RuntimeError):
    pass


class ProfileResolution(NamedTuple):
    patch: str
    head: str
    intro: str
    base: str
    ref: str
    kernel_target: str
    files: list[str]
    hunks: int
    profile_hunks: int
    excluded_thp_hunks: int
    compatibility_sources: list[dict[str, Any]]


def _remaining_timeout(requested: int) -> int:
    if _RESOLVE_DEADLINE is None:
        return requested
    remaining = int(_RESOLVE_DEADLINE - time.monotonic())
    if remaining <= 0:
        raise ResolveError(
            f"Zen interactive resolution exceeded {TOTAL_RESOLVE_TIMEOUT} seconds"
        )
    return max(1, min(requested, remaining))


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
) -> str:
    effective_timeout = _remaining_timeout(timeout)
    command = shlex.join(args)
    print(f"==> Zen resolver: {command} (timeout {effective_timeout}s)", flush=True)
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", "1024")
    env.setdefault("GIT_HTTP_LOW_SPEED_TIME", "30")
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ResolveError(
            f"command timed out after {effective_timeout}s: {command}"
        ) from exc
    elapsed = time.monotonic() - started
    if completed.returncode:
        raise ResolveError(
            f"command failed ({completed.returncode}) after {elapsed:.1f}s: {command}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    print(f"==> Zen resolver command completed in {elapsed:.1f}s", flush=True)
    return completed.stdout


def series_key(series: str) -> tuple[int, int]:
    if not SERIES_RE.fullmatch(series):
        raise ResolveError(f"invalid kernel series: {series!r}")
    major, minor = (int(part) for part in series.split("."))
    return major, minor


def requested_kernel_series() -> str:
    return os.environ.get("KERNEL_SERIES", DEFAULT_KERNEL_SERIES)


def parse_zen_refs(output: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        match = ZEN_REF_RE.fullmatch(fields[1])
        if match:
            refs[match.group(1)] = fields[1].removeprefix("refs/heads/")
    return refs


def select_compatible_ref(kernel_series: str | None = None) -> tuple[str, str, str]:
    """Return ``(ref, source_series, selection)`` for the target series.

    The exact series is preferred. If Zen has not published that branch yet,
    the newest older Zen series is selected; a newer branch is never applied to
    an older stable kernel. This keeps every build on the newest compatible
    official source without hard-coding a stale branch name.
    """
    target = kernel_series or requested_kernel_series()
    target_key = series_key(target)
    raw_refs = run(
        ["git", "ls-remote", "--heads", REPO, "refs/heads/*/zen-sauce"],
        timeout=FETCH_TIMEOUT,
    )
    refs = parse_zen_refs(raw_refs)
    if not refs:
        raise ResolveError("official Zen repository has no zen-sauce series branches")

    exact = refs.get(target)
    if exact:
        return exact, target, "exact-series"

    compatible = [
        (series_key(series), series)
        for series in refs
        if series_key(series) <= target_key
    ]
    if not compatible:
        available = ", ".join(sorted(refs, key=series_key))
        raise ResolveError(
            f"no Zen zen-sauce branch is compatible with Linux {target}; "
            f"available series: {available}"
        )
    _, selected = max(compatible)
    return refs[selected], selected, "nearest-older-series"


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
            lines.append(prefix + "\t    Transparent memory-page policy....: unchanged" + ending)
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
    if SYMBOL_DEFINITION not in result:
        raise ResolveError("official profile patch does not define config ZEN_INTERACTIVE")
    if result.count(SYMBOL) < 2:
        raise ResolveError("official profile contains too few ZEN_INTERACTIVE references")
    assert_thp_untouched(result)
    return result, files, kept_hunks, excluded_thp_hunks


def read_file_at(checkout: Path, commit: str, path: str) -> str:
    return run(["git", "show", f"{commit}:{path}"], cwd=checkout)


def locate_introduction(checkout: Path) -> str | None:
    # The official Zen profile has a stable introduction subject. Commit
    # metadata is cheap to walk even in a blob-less clone; verify the selected
    # commit and its parent below so a future subject change remains safe.
    commits = run(
        [
            "git",
            "log",
            "--reverse",
            "--format=%H",
            "--fixed-strings",
            "--grep",
            INTRODUCTION_SUBJECT,
            "FETCH_HEAD",
            "--",
            "init/Kconfig",
        ],
        cwd=checkout,
    ).splitlines()
    if not commits:
        # If the upstream subject changes, fall back to Git's semantic search.
        # Iterating over every historical init/Kconfig blob would turn a
        # blob-less clone into one network request per commit.
        commits = run(
            [
                "git",
                "log",
                "--reverse",
                "--format=%H",
                "-S",
                SYMBOL_DEFINITION,
                "FETCH_HEAD",
                "--",
                "init/Kconfig",
            ],
            cwd=checkout,
        ).splitlines()
    if not commits:
        # A shallow boundary can contain the symbol without its introduction
        # commit. The caller will deepen the history and try again.
        return None

    commit = commits[0].strip()
    current = read_file_at(checkout, commit, "init/Kconfig")
    if SYMBOL_DEFINITION not in current:
        return None
    parent_check = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^"],
        cwd=checkout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=_remaining_timeout(DEFAULT_COMMAND_TIMEOUT),
    )
    if parent_check.returncode != 0:
        return None
    previous = read_file_at(checkout, f"{commit}^", "init/Kconfig")
    return commit if SYMBOL_DEFINITION not in previous else None


def discover_symbol_files(checkout: Path, *, intro: str, head: str) -> list[str]:
    # The introduction commit is the authoritative profile boundary. Inspect only
    # the files changed by that commit at current HEAD. This avoids `git grep` over
    # the entire Linux tree, which causes a blob-less partial clone to lazily fetch
    # tens of thousands of objects and can stall GitHub-hosted runners for hours.
    introduced_paths = run(
        [
            "git",
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            intro,
        ],
        cwd=checkout,
    ).splitlines()
    if not introduced_paths:
        raise ResolveError("ZEN_INTERACTIVE introduction commit changed no files")

    selected: list[str] = []
    for path in introduced_paths:
        try:
            content = read_file_at(checkout, head, path)
        except ResolveError as exc:
            if "does not exist" in str(exc):
                continue
            raise
        if SYMBOL in content:
            selected.append(path)

    if "init/Kconfig" not in selected:
        raise ResolveError("current official profile no longer defines ZEN_INTERACTIVE")
    if len(selected) < 2:
        raise ResolveError("official profile resolves to too few symbol-bearing files")
    return sorted(set(selected))


def discover_compatibility_sources(
    checkout: Path, *, head: str
) -> list[dict[str, Any]]:
    """Find the current Zen commits omitted by the symbol-gated profile.

    These are selected from the history of the chosen official series branch,
    not copied into this repository as fixed patch files. The resulting commit
    and byte hashes are recorded in the per-build lock after materialization.
    """
    sources: list[dict[str, Any]] = []
    for spec in COMPATIBILITY_SPECS:
        commits = run(
            [
                "git",
                "log",
                "--format=%H",
                "-G",
                spec["pattern"],
                head,
                "--",
                spec["path"],
            ],
            cwd=checkout,
            timeout=FETCH_TIMEOUT,
        ).splitlines()
        if not commits:
            raise ResolveError(
                f"Zen series history has no {spec['name']} compatibility commit"
            )

        commit = commits[0].strip()
        parent = run(
            ["git", "rev-parse", f"{commit}^"],
            cwd=checkout,
        ).strip()
        patch = run(
            [
                "git",
                "diff",
                "--full-index",
                "--no-ext-diff",
                "--no-renames",
                parent,
                commit,
                "--",
                spec["path"],
            ],
            cwd=checkout,
            timeout=FETCH_TIMEOUT,
        )
        if not patch or "diff --git " not in patch:
            raise ResolveError(
                f"Zen compatibility commit {commit} produced no patch for "
                f"{spec['path']}"
            )
        if spec["marker"] not in patch:
            raise ResolveError(
                f"Zen compatibility commit {commit} does not contain the expected "
                f"{spec['name']} marker"
            )
        assert_thp_untouched(patch)
        subject = run(
            ["git", "show", "-s", "--format=%s", commit],
            cwd=checkout,
        ).strip()
        sources.append(
            {
                "name": spec["name"],
                "path": spec["path"],
                "commit": commit,
                "parent_commit": parent,
                "subject": subject,
                "selection": "latest matching commit on selected official Zen series",
                "sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                "size": len(patch.encode("utf-8")),
                "patch": patch,
            }
        )
    return sources


def fetch_profile(checkout: Path) -> ProfileResolution:
    kernel_target = requested_kernel_series()
    ref, _source_series, _selection = select_compatible_ref(kernel_target)
    shutil.rmtree(checkout, ignore_errors=True)
    checkout.mkdir(parents=True)
    run(["git", "init", "--quiet"], cwd=checkout)
    run(["git", "remote", "add", "origin", REPO], cwd=checkout)
    run(["git", "config", "remote.origin.promisor", "true"], cwd=checkout)
    run(["git", "config", "remote.origin.partialclonefilter", "blob:none"], cwd=checkout)

    depth = 128
    intro = ""
    compatibility_sources: list[dict[str, Any]] = []
    while depth <= MAX_HISTORY_DEPTH:
        print(f"==> Zen resolver: fetching {ref} at depth {depth}", flush=True)
        run(
            [
                "git",
                "fetch",
                "--force",
                "--no-tags",
                f"--depth={depth}",
                "--filter=blob:none",
                "origin",
                f"refs/heads/{ref}",
            ],
            cwd=checkout,
            timeout=FETCH_TIMEOUT,
        )
        intro = locate_introduction(checkout) or ""
        if intro:
            parent_check = subprocess.run(
                ["git", "cat-file", "-e", f"{intro}^"],
                cwd=checkout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=_remaining_timeout(DEFAULT_COMMAND_TIMEOUT),
            )
            if parent_check.returncode == 0:
                try:
                    compatibility_sources = discover_compatibility_sources(
                        checkout, head="FETCH_HEAD"
                    )
                except ResolveError as exc:
                    if depth < MAX_HISTORY_DEPTH:
                        print(
                            "==> Zen resolver: compatibility history is outside "
                            f"depth {depth}; deepening ({exc})",
                            flush=True,
                        )
                        depth *= 2
                        continue
                    raise
                break
        depth *= 2
    else:
        raise ResolveError("could not locate the complete ZEN_INTERACTIVE introduction history")

    head = run(["git", "rev-parse", "FETCH_HEAD"], cwd=checkout).strip()
    base = run(["git", "rev-parse", f"{intro}^"], cwd=checkout).strip()
    symbol_files = discover_symbol_files(checkout, intro=intro, head=head)

    full_diff = run(
        [
            "git",
            "diff",
            "--full-index",
            "--no-ext-diff",
            "--no-renames",
            base,
            head,
            "--",
            *symbol_files,
        ],
        cwd=checkout,
        timeout=FETCH_TIMEOUT,
    )
    patch, selected_files, hunks, excluded = filter_symbol_hunks(full_diff)
    compatibility_patch = "\n".join(
        source["patch"].rstrip("\n") for source in compatibility_sources
    )
    if compatibility_patch:
        patch = patch.rstrip("\n") + "\n" + compatibility_patch + "\n"
    assert_thp_untouched(patch)
    compatibility_files = [source["path"] for source in compatibility_sources]
    total_hunks = patch.count("\n@@ ")
    return ProfileResolution(
        patch=patch,
        head=head,
        intro=intro,
        base=base,
        ref=ref,
        kernel_target=kernel_target,
        files=sorted(set(selected_files + compatibility_files)),
        hunks=total_hunks,
        profile_hunks=hunks,
        excluded_thp_hunks=excluded,
        compatibility_sources=compatibility_sources,
    )


def update_lock(
    path: Path,
    *,
    output: Path,
    resolution: ProfileResolution,
) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    components = data.setdefault("components", {})
    content = output.read_bytes()
    components["zen_interactive"] = {
        "kind": "git_profile",
        "repo": REPO,
        "ref": resolution.ref,
        "commit": resolution.head,
        "base_commit": resolution.base,
        "introduction_commit": resolution.intro,
        "kernel_target": resolution.kernel_target,
        "selection": (
            "exact-series-profile"
            if resolution.ref == f"{resolution.kernel_target}/zen-sauce"
            else "nearest-older-series-profile"
        ),
        "output": str(output),
        "files": resolution.files,
        "hunks": resolution.hunks,
        "profile_hunks": resolution.profile_hunks,
        "excluded_thp_hunks": resolution.excluded_thp_hunks,
        "thp_policy": "preserved-unchanged",
        "compatibility_sources": [
            {key: value for key, value in source.items() if key != "patch"}
            for source in resolution.compatibility_sources
        ],
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

    global _RESOLVE_DEADLINE
    _RESOLVE_DEADLINE = time.monotonic() + TOTAL_RESOLVE_TIMEOUT

    try:
        resolution = fetch_profile(args.checkout)
    except ResolveError as exc:
        raise SystemExit(f"Zen interactive resolver failed: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(resolution.patch, encoding="utf-8")
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.provenance.write_text(
        "\n".join(
            [
                "Component: Zen interactive tuning profile",
                f"Repository: {REPO}",
                f"Ref: {resolution.ref}",
                f"Commit: {resolution.head}",
                f"Introduction commit: {resolution.intro}",
                f"Diff base: {resolution.base}",
                f"Kernel target: {resolution.kernel_target}",
                "Selection: newest exact or nearest older official series",
                "Discovery: introduction-commit files at current HEAD",
                "Compatibility commits: latest matching history on selected series",
                "THP policy: preserved unchanged; all THP hunks excluded",
                f"Excluded THP hunks: {resolution.excluded_thp_hunks}",
                f"Files: {', '.join(resolution.files)}",
                f"Profile hunks: {resolution.profile_hunks}",
                f"Total hunks: {resolution.hunks}",
                f"SHA256: {digest}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with args.provenance.open("a", encoding="utf-8") as provenance:
        for source in resolution.compatibility_sources:
            provenance.write(
                "Compatibility commit: "
                f"{source['name']} {source['commit']} "
                f"({source['path']}) {source['subject']}\n"
            )
            provenance.write(f"Compatibility SHA256: {source['sha256']}\n")
    update_lock(
        args.lock,
        output=args.output,
        resolution=resolution,
    )
    print(
        f"Resolved official Zen interactive profile {resolution.head} from "
        f"{resolution.ref}: {resolution.hunks} hunks in {len(resolution.files)} "
        f"files; added {len(resolution.compatibility_sources)} compatibility "
        f"commits; excluded {resolution.excluded_thp_hunks} THP hunks",
        flush=True,
    )


if __name__ == "__main__":
    main()
