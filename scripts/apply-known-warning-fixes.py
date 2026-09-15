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


def insert_after_exact_line_once(text: str, line: str, addition: str, label: str) -> str:
    lines = text.splitlines(keepends=True)
    matches = [i for i, candidate in enumerate(lines) if candidate.rstrip("\r\n") == line]
    if len(matches) != 1:
        raise RewriteError(f"{label}: expected one exact line {line!r}, found {len(matches)}")
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
import re, sys
path = Path(sys.argv[1]); text = path.read_text(encoding="utf-8")
text, replacements = re.compile(r"^int futex_opcode_31\(", re.MULTILINE).subn("static int futex_opcode_31(", text)
if replacements > 1: raise SystemExit(f"unexpected futex_opcode_31 definition count: {replacements}")
path.write_text(text, encoding="utf-8")
PYFIX
  if grep -Fq 'futex_opcode_31(' "$futex_source"; then
    grep -Fq 'static int futex_opcode_31(' "$futex_source"
    ! grep -Eq '^int futex_opcode_31\(' "$futex_source"
  fi
  python3 - "$gud_source" <<'PYGUD'
from pathlib import Path
import sys
path = Path(sys.argv[1]); text = path.read_text(encoding="utf-8"); changes = 0
def replace_optional(old, new, label):
    global text, changes
    if new in text: return
    if text.count(old) != 1: raise SystemExit(f"{label}: expected one source anchor, found {text.count(old)}")
    text = text.replace(old, new, 1); changes += 1
replace_optional("\tsize_t buf_len = GUD_CONNECTOR_TV_MODE_MAX_NUM * GUD_CONNECTOR_TV_MODE_NAME_LEN;\n\tconst char *modes[GUD_CONNECTOR_TV_MODE_MAX_NUM];\n\tunsigned int i, num_modes;\n\tchar *buf;\n\tint ret;", "\tsize_t buf_len = GUD_CONNECTOR_TV_MODE_MAX_NUM * GUD_CONNECTOR_TV_MODE_NAME_LEN;\n\tconst char *modes[GUD_CONNECTOR_TV_MODE_MAX_NUM];\n\tunsigned int i, num_modes;\n\tchar (*buf)[GUD_CONNECTOR_TV_MODE_NAME_LEN];\n\tint ret;", "GUD typed TV-mode slot declaration")
replace_optional("\tbuf = kmalloc(buf_len, GFP_KERNEL);", "\tbuf = kmalloc_array(GUD_CONNECTOR_TV_MODE_MAX_NUM, sizeof(*buf), GFP_KERNEL);", "GUD typed TV-mode allocation")
old_check = "if (!ret || ret % GUD_CONNECTOR_TV_MODE_NAME_LEN) {"; new_check = "if (!ret || ret > buf_len || ret % GUD_CONNECTOR_TV_MODE_NAME_LEN) {"
if new_check not in text:
    if text.count(old_check) != 1: raise SystemExit("GUD TV-mode bounds anchor changed")
    text = text.replace(old_check, new_check, 1); changes += 1
replace_optional("\tnum_modes = ret / GUD_CONNECTOR_TV_MODE_NAME_LEN;", "\tnum_modes = ret / sizeof(*buf);", "GUD TV-mode count")
replace_optional("\t\tchar *mode = &buf[i * GUD_CONNECTOR_TV_MODE_NAME_LEN];", "\t\tchar *mode = buf[i];", "GUD slot selection")
replace_optional("\t\tif (!memchr(mode, '\\0', GUD_CONNECTOR_TV_MODE_NAME_LEN)) {", "\t\tif (!memchr(mode, '\\0', sizeof(*buf))) {", "GUD memchr bound")
path.write_text(text, encoding="utf-8"); print(f"GUD TV-mode typed-slot Full-LTO fix changes={changes}")
PYGUD
  grep -Fq 'char (*buf)[GUD_CONNECTOR_TV_MODE_NAME_LEN]' "$gud_source"
  grep -Fq 'ret > buf_len' "$gud_source"
  grep -Fq "memchr(mode, '\\0', sizeof(*buf))" "$gud_source"
  git diff --check -- "$futex_source" "$gud_source"
  { echo "futex_opcode_31 linkage: translation-unit local"; echo "GUD TV-mode response: typed fixed-size slots plus explicit ret <= buf_len invariant for Full LTO/FORTIFY"; } | tee "$LOGDIR/known-warning-fixes.txt"
}

'''
    text = replace_once(text, "normalize_changed_whitespace() {\n", function + "normalize_changed_whitespace() {\n", "known warning fix function")
    text = insert_after_exact_line_once(text, "apply_requested_patch_series", "fix_known_build_warnings\n", "known warning fix call")
    text = insert_after_exact_line_once(text, "configure_builtin_cmdline", "\n# MULTIPLEXER is hidden; MUX_CORE is its public selector.\nscripts/config --enable MUX_CORE\n", "MUX core configuration")
    text = insert_after_exact_line_once(text, 'assert_config "CONFIG_CMDLINE_BOOL=y"', 'assert_config "CONFIG_MUX_CORE=y"\nassert_config "CONFIG_MULTIPLEXER=y"\n', "MUX framework assertions")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2: raise SystemExit("usage: apply-known-warning-fixes.py <generated-core>")
    try: rewrite(Path(sys.argv[1]))
    except RewriteError as exc: raise SystemExit(f"Known warning rewrite failed: {exc}") from exc

if __name__ == "__main__": main()
