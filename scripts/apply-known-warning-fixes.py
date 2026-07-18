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
    text = replace_once(
        text,
        "apply_requested_patch_series\n\n# Generic amd64 profile:",
        "apply_requested_patch_series\nfix_known_build_warnings\n\n# Generic amd64 profile:",
        "known warning fix call",
    )
    text = replace_once(
        text,
        "configure_builtin_cmdline\n\n# PR validation",
        "configure_builtin_cmdline\n\n# MULTIPLEXER is a boolean symbol. Liquorix may carry the stale module value,\n# which olddefconfig normalizes with a warning unless corrected first.\nscripts/config --enable MULTIPLEXER\n\n# PR validation",
        "MULTIPLEXER configuration",
    )
    text = replace_once(
        text,
        'assert_config "CONFIG_CMDLINE_BOOL=y"\n',
        'assert_config "CONFIG_CMDLINE_BOOL=y"\nassert_config "CONFIG_MULTIPLEXER=y"\n',
        "MULTIPLEXER assertion",
    )
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
