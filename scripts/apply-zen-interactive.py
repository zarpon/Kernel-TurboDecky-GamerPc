#!/usr/bin/env python3
"""Integrate the official Zen interactive profile into the generated build."""
from __future__ import annotations

import argparse
from pathlib import Path


class RewriteError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RewriteError(f"expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def rewrite(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    variables_marker = 'ZEN_INTERACTIVE_REF="7.0/zen-sauce"\n'
    if variables_marker not in text:
        anchor = (
            'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256='
            '"cdf138cdb94fcb4e2988bd7d2873a51522fdb7212ec314fde202facaf8210b5c"\n'
        )
        replacement = anchor + '''
# Zen has not published a 7.1 sauce branch yet. Follow the current official
# 7.0 profile and port only hunks explicitly gated by ZEN_INTERACTIVE.
ZEN_INTERACTIVE_REPO="https://github.com/zen-kernel/zen-kernel.git"
ZEN_INTERACTIVE_REF="7.0/zen-sauce"
ZEN_INTERACTIVE_DIR="$WORKDIR/zen-interactive"
ZEN_INTERACTIVE_PATCH="$PATCHDIR/00-zen-interactive-profile.patch"
ZEN_INTERACTIVE_PROVENANCE="$LOGDIR/00-zen-interactive-provenance.txt"
'''
        text = replace_once(text, anchor, replacement, "Zen variables")

    function_marker = "apply_zen_interactive_profile() {\n"
    if function_marker not in text:
        anchor = "assert_config() {\n"
        functions = r'''fetch_zen_interactive_profile() {
  echo "==> Resolving the current official Zen interactive profile"
  python3 "$ROOT/scripts/resolve-zen-interactive-fast.py" \
    --checkout "$ZEN_INTERACTIVE_DIR" \
    --output "$ZEN_INTERACTIVE_PATCH" \
    --provenance "$ZEN_INTERACTIVE_PROVENANCE" \
    --lock "$LOGDIR/patch-lock.json"
}

report_zen_interactive_rejects() {
  {
    echo "==> Unresolved Zen interactive profile port rejects"
    find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
    echo
    while IFS= read -r reject; do
      echo "### ${reject#$KERNELDIR/}"
      cat "$reject"
    done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
  } | tee "$LOGDIR/00-zen-interactive-port-rejects.log"
}

assert_zen_patch_does_not_touch_thp() {
  local file="$1"
  if grep -Fq 'diff --git a/mm/huge_memory.c b/mm/huge_memory.c' "$file"; then
    echo "Zen profile must not modify mm/huge_memory.c" >&2
    return 1
  fi
  if grep -E '^[+-].*(TRANSPARENT_HUGEPAGE|khugepaged|THP_)' "$file"; then
    echo "Zen profile must not modify THP symbols or defaults" >&2
    return 1
  fi
}

apply_zen_interactive_profile() {
  local file="$1" status=0 thp_before thp_after

  assert_zen_patch_does_not_touch_thp "$file"
  thp_before="$(sha256sum mm/huge_memory.c | awk '{print $1}')"

  echo "==> Applying the official CONFIG_ZEN_INTERACTIVE profile without THP changes"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/00-zen-interactive.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/00-zen-interactive.apply.log"
  else
    cat "$LOGDIR/00-zen-interactive.dry-run.log"
    echo "==> Porting Zen interactive profile from Linux 7.0 to $KERNEL_VERSION"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/00-zen-interactive.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/00-zen-interactive.fuzz-apply.log"
    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      report_zen_interactive_rejects
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  normalize_changed_whitespace
  git diff --check | tee "$LOGDIR/00-zen-interactive-diff-check.log"

  thp_after="$(sha256sum mm/huge_memory.c | awk '{print $1}')"
  if [[ "$thp_before" != "$thp_after" ]]; then
    echo "Zen profile changed mm/huge_memory.c despite the THP exclusion policy" >&2
    return 1
  fi
  printf '%s  mm/huge_memory.c\n' "$thp_after" \
    | tee "$LOGDIR/00-zen-interactive-thp-preserved.sha256"

  grep -Fq 'config ZEN_INTERACTIVE' init/Kconfig
  grep -R -Fq 'CONFIG_ZEN_INTERACTIVE' arch block drivers init kernel mm
  echo "==> Zen interactive profile applied successfully; THP preserved unchanged"
}

'''
        text = replace_once(text, anchor, functions + anchor, "Zen functions")

    fetch_marker = "fetch_zen_interactive_profile\n\ncd \"$KERNELDIR\"\n"
    if fetch_marker not in text:
        anchor = '\ncd "$KERNELDIR"\n'
        replacement = '\nfetch_zen_interactive_profile\n\ncd "$KERNELDIR"\n'
        text = replace_once(text, anchor, replacement, "Zen fetch boundary")

    apply_marker = 'apply_zen_interactive_profile "$ZEN_INTERACTIVE_PATCH"\n\ncp '
    if apply_marker not in text:
        anchor = 'cp "$WORKDIR/liquorix-amd64.config" .config\n'
        replacement = (
            'apply_zen_interactive_profile "$ZEN_INTERACTIVE_PATCH"\n\n'
            'cp "$WORKDIR/liquorix-amd64.config" .config\n'
        )
        text = replace_once(text, anchor, replacement, "Zen apply call")

    config_old = (
        'scripts/config --enable SCHED_BORE\n'
        'scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n'
    )
    config_new = config_old + 'scripts/config --enable ZEN_INTERACTIVE\n'
    if config_new not in text:
        text = replace_once(text, config_old, config_new, "Zen config")

    assert_old = 'assert_config "CONFIG_SCHED_BORE=y"\n'
    assert_new = assert_old + 'assert_config "CONFIG_ZEN_INTERACTIVE=y"\n'
    if assert_new not in text:
        text = replace_once(text, assert_old, assert_new, "Zen assertion")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_core", type=Path)
    args = parser.parse_args()
    try:
        rewrite(args.build_core)
    except RewriteError as exc:
        raise SystemExit(f"Zen interactive rewrite failed: {exc}") from exc


if __name__ == "__main__":
    main()
