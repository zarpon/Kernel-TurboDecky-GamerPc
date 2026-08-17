#!/usr/bin/env python3
"""Rewrite the generated kernel build to eliminate known source/config warnings."""
from __future__ import annotations

import sys
from pathlib import Path


class RewriteError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RewriteError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def insert_after_exact_line_once(
    text: str, line: str, addition: str, label: str
) -> str:
    """Insert after one exact shell line without depending on surrounding blocks."""
    lines = text.splitlines(keepends=True)
    matches = [
        index
        for index, candidate in enumerate(lines)
        if candidate.rstrip("\r\n") == line
    ]
    if len(matches) != 1:
        raise RewriteError(
            f"{label}: expected one exact line {line!r}, found {len(matches)}"
        )
    if addition and not addition.endswith("\n"):
        addition += "\n"
    lines.insert(matches[0] + 1, addition)
    return "".join(lines)


def rewrite_shellcheck_clean_constructs(text: str) -> str:
    """Keep generated shell strict without suppressing legitimate ShellCheck checks."""
    # SC2016 flags awk's intentional $1 because the awk program is nested in a
    # double-quoted command substitution. sha256sum output is space-delimited,
    # so cut expresses the same first-field operation without an embedded '$'.
    text = text.replace("| awk '{print $1}'", "| cut -d ' ' -f1")

    # Likewise, use a double-quoted sed expression with escaped literal quotes.
    # This preserves the end-of-line '$' regex while avoiding SC2016 on the
    # single-quoted expression nested inside a double-quoted substitution.
    old = '''sed 's/^CONFIG_CMDLINE="//; s/"$//' '''.rstrip()
    new = r'''sed "s/^CONFIG_CMDLINE=\"//; s/\"$//"'''
    # The raw string above must not escape the shell's outer quotes.
    new = new.replace('sed \\"', 'sed "').replace('$//\\"', '$//"')
    if old not in text:
        raise RewriteError("CONFIG_CMDLINE ShellCheck cleanup anchor is missing")
    return text.replace(old, new)


def rewrite(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "fix_known_build_warnings() {"
    if marker in text:
        return

    function = r'''fix_known_build_warnings() {
  local futex_source="kernel/futex/syscalls.c"

  echo "==> Fixing known source and configuration warnings"
  python3 - "$futex_source" <<'PYFIX'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
pattern = re.compile(r"^int futex_opcode_31\(", re.MULTILINE)
text, replacements = pattern.subn("static int futex_opcode_31(", text)
if replacements > 1:
    raise SystemExit(f"unexpected futex_opcode_31 definition count: {replacements}")
path.write_text(text, encoding="utf-8")
PYFIX

  if grep -Fq 'futex_opcode_31(' "$futex_source"; then
    grep -Fq 'static int futex_opcode_31(' "$futex_source"
    ! grep -Eq '^int futex_opcode_31\(' "$futex_source"
  fi

  echo "futex_opcode_31 linkage: translation-unit local" \
    | tee "$LOGDIR/known-warning-fixes.txt"
}

'''
    text = replace_once(
        text,
        "normalize_changed_whitespace() {\n",
        function + "normalize_changed_whitespace() {\n",
        "known warning fix function",
    )
    text = insert_after_exact_line_once(
        text,
        "apply_requested_patch_series",
        "fix_known_build_warnings\n",
        "known warning fix call",
    )
    text = insert_after_exact_line_once(
        text,
        "configure_builtin_cmdline",
        "\n# MULTIPLEXER is a boolean symbol. Liquorix may carry the stale module value,\n"
        "# which olddefconfig normalizes with a warning unless corrected first.\n"
        "scripts/config --enable MULTIPLEXER\n",
        "MULTIPLEXER configuration",
    )
    text = insert_after_exact_line_once(
        text,
        'assert_config "CONFIG_CMDLINE_BOOL=y"',
        'assert_config "CONFIG_MULTIPLEXER=y"\n',
        "MULTIPLEXER assertion",
    )
    text = rewrite_shellcheck_clean_constructs(text)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-known-warning-fixes.py <generated-core>")
    try:
        rewrite(Path(sys.argv[1]))
    except RewriteError as exc:
        raise SystemExit(f"Known warning rewrite failed: {exc}") from exc


if __name__ == "__main__":
    main()
