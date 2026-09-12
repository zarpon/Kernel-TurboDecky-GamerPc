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


def rewrite(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "fix_known_build_warnings() {"
    if marker in text:
        return

    function = r'''fix_known_build_warnings() {
  local futex_source="kernel/futex/syscalls.c"
  local gud_source="drivers/gpu/drm/gud/gud_connector.c"

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

  # Linux 7.2.5 can expose a Full-LTO/FORTIFY __read_overflow failure while
  # linking gud.o. Merely checking ret <= buf_len is insufficient because LTO
  # still loses the per-slot object bound after pointer arithmetic. Model the
  # allocation as an array of fixed-size TV-mode-name slots instead. Each
  # memchr() then operates on exactly one typed slot, preserving GUD semantics
  # while giving FORTIFY a statically provable object size.
  python3 - "$gud_source" <<'PYGUD'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
changes = 0


def replace_optional(old: str, new: str, label: str) -> None:
    global text, changes
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source anchor, found {count}")
    text = text.replace(old, new, 1)
    changes += 1


replace_optional(
    "\tsize_t buf_len = GUD_CONNECTOR_TV_MODE_MAX_NUM * GUD_CONNECTOR_TV_MODE_NAME_LEN;\n"
    "\tconst char *modes[GUD_CONNECTOR_TV_MODE_MAX_NUM];\n"
    "\tunsigned int i, num_modes;\n"
    "\tchar *buf;\n"
    "\tint ret;",
    "\tsize_t buf_len = GUD_CONNECTOR_TV_MODE_MAX_NUM * GUD_CONNECTOR_TV_MODE_NAME_LEN;\n"
    "\tconst char *modes[GUD_CONNECTOR_TV_MODE_MAX_NUM];\n"
    "\tunsigned int i, num_modes;\n"
    "\tchar (*buf)[GUD_CONNECTOR_TV_MODE_NAME_LEN];\n"
    "\tint ret;",
    "GUD typed TV-mode slot declaration",
)
replace_optional(
    "\tbuf = kmalloc(buf_len, GFP_KERNEL);",
    "\tbuf = kmalloc_array(GUD_CONNECTOR_TV_MODE_MAX_NUM, sizeof(*buf), GFP_KERNEL);",
    "GUD typed TV-mode allocation",
)

old_check = "if (!ret || ret % GUD_CONNECTOR_TV_MODE_NAME_LEN) {"
new_check = "if (!ret || ret > buf_len || ret % GUD_CONNECTOR_TV_MODE_NAME_LEN) {"
if new_check not in text:
    if text.count(old_check) != 1:
        raise SystemExit("GUD TV-mode bounds anchor changed; refusing an unreviewed source rewrite")
    text = text.replace(old_check, new_check, 1)
    changes += 1

replace_optional(
    "\tnum_modes = ret / GUD_CONNECTOR_TV_MODE_NAME_LEN;",
    "\tnum_modes = ret / sizeof(*buf);",
    "GUD TV-mode count from typed slot size",
)
replace_optional(
    "\t\tchar *mode = &buf[i * GUD_CONNECTOR_TV_MODE_NAME_LEN];",
    "\t\tchar *mode = buf[i];",
    "GUD typed TV-mode slot selection",
)
replace_optional(
    "\t\tif (!memchr(mode, '\\0', GUD_CONNECTOR_TV_MODE_NAME_LEN)) {",
    "\t\tif (!memchr(mode, '\\0', sizeof(*buf))) {",
    "GUD FORTIFY-visible memchr slot bound",
)

required = (
    "char (*buf)[GUD_CONNECTOR_TV_MODE_NAME_LEN]",
    "kmalloc_array(GUD_CONNECTOR_TV_MODE_MAX_NUM, sizeof(*buf), GFP_KERNEL)",
    "ret > buf_len",
    "num_modes = ret / sizeof(*buf)",
    "char *mode = buf[i]",
    "memchr(mode, '\\0', sizeof(*buf))",
)
for marker in required:
    if text.count(marker) != 1:
        raise SystemExit(f"unexpected GUD typed-slot marker count for {marker!r}: {text.count(marker)}")

path.write_text(text, encoding="utf-8")
print(f"GUD TV-mode typed-slot Full-LTO fix changes={changes}")
PYGUD

  grep -Fq 'char (*buf)[GUD_CONNECTOR_TV_MODE_NAME_LEN]' "$gud_source"
  grep -Fq 'ret > buf_len' "$gud_source"
  grep -Fq "memchr(mode, '\\0', sizeof(*buf))" "$gud_source"
  git diff --check -- "$futex_source" "$gud_source"

  {
    echo "futex_opcode_31 linkage: translation-unit local"
    echo "GUD TV-mode response: typed fixed-size slots plus explicit ret <= buf_len invariant for Full LTO/FORTIFY"
  } | tee "$LOGDIR/known-warning-fixes.txt"
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
