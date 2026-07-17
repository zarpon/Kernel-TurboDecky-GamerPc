#!/usr/bin/env python3
"""Inject the pinned VRAM/DMEM kernel port and userspace package into the build wrapper."""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "# TurboDecky VRAM/DMEM integration"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-vram-cgroup.py <build-kernelnote.sh>")

    path = Path(sys.argv[1])
    wrapper = path.read_text(encoding="utf-8")
    if MARKER in wrapper:
        print("VRAM/DMEM build integration already present")
        return

    injection = r"""
# TurboDecky VRAM/DMEM integration
replace_once(
    'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"\n',
    '''NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"

# VRAM cgroup-aware TTM eviction and allocation policy. The source file is the
# CachyOS aggregation of pixelcluster's six upstream commits, pinned exactly.
VRAM_PATCH_REPO="https://github.com/CachyOS/kernel-patches.git"
VRAM_PATCH_COMMIT="ea739d734ec179864b21446856315bc49f7c52fa"
VRAM_PATCH_PATH="7.0/misc/0001-cgroup-vram.patch"
VRAM_PATCH_DIR="$WORKDIR/cachyos-vram-patches"
VRAM_PATCH="$PATCHDIR/0007-cgroup-vram-linux7.1-port.patch"
'''
)

replace_once(
    'normalize_changed_whitespace() {\n',
    r'''fetch_vram_patch() {
  echo "==> Fetching pinned VRAM cgroup/TTM patch source"
  rm -rf "$VRAM_PATCH_DIR"
  git init --quiet "$VRAM_PATCH_DIR"
  git -C "$VRAM_PATCH_DIR" remote add origin "$VRAM_PATCH_REPO"
  git -C "$VRAM_PATCH_DIR" config remote.origin.promisor true
  git -C "$VRAM_PATCH_DIR" config remote.origin.partialclonefilter blob:none
  git -C "$VRAM_PATCH_DIR" fetch --no-tags --depth=1 --filter=blob:none \
    origin "$VRAM_PATCH_COMMIT" 2>&1 | tee "$LOGDIR/07-vram-fetch.log"
  git -C "$VRAM_PATCH_DIR" show "FETCH_HEAD:$VRAM_PATCH_PATH" > "$VRAM_PATCH"
  test -s "$VRAM_PATCH"
  grep -Fq 'Subject: [PATCH] cgroup-vram' "$VRAM_PATCH"
  grep -Fq 'struct ttm_bo_alloc_state' "$VRAM_PATCH"
  grep -Fq 'dmem_cgroup_get_common_ancestor' "$VRAM_PATCH"
  {
    echo "Component: cgroup-aware VRAM management"
    echo "Aggregation repository: $VRAM_PATCH_REPO"
    echo "Aggregation commit: $VRAM_PATCH_COMMIT"
    echo "Aggregation path: $VRAM_PATCH_PATH"
    echo "Aggregation SHA256: $(sha256sum "$VRAM_PATCH" | awk '{print $1}')"
    echo "Pixelcluster upstream commits:"
    echo "  9d928b2c5af078304205c12c71fec4904860d8cc"
    echo "  9a02490c9f7938a4ed8950f0d61bcf677f67c07b"
    echo "  1f24ddd4ffd04f47a04bd84987f36dc545bc7421"
    echo "  f6bde8345b0c66e9cd81fa368343d4438ac9b3b0"
    echo "  68f051af747220ac7d1d74bec8d79f2cb3a58304"
    echo "  9260440455cd61f2c90cca172bc9d3e83bf1206d"
  } | tee "$LOGDIR/07-vram-provenance.txt"
}

normalize_changed_whitespace() {
'''
)

replace_once(
    'apply_infinity_patch() {\n',
    r'''apply_vram_patch() {
  local file="$1"
  local markers=0

  grep -Fq 'struct ttm_bo_alloc_state' drivers/gpu/drm/ttm/ttm_bo.c && markers=$((markers + 1))
  grep -Fq 'dmem_cgroup_below_min' kernel/cgroup/dmem.c && markers=$((markers + 1))
  grep -Fq 'cgroup_common_ancestor' include/linux/cgroup.h && markers=$((markers + 1))

  if ((markers == 3)); then
    echo "==> VRAM cgroup/TTM policy already integrated upstream"
  elif ((markers != 0)); then
    echo "Partial VRAM cgroup/TTM integration detected; refusing mixed source" >&2
    return 1
  else
    echo "==> Applying cgroup-aware VRAM allocation and eviction policy"
    if patch --batch --forward --strip=1 --dry-run < "$file" \
        > "$LOGDIR/07-vram.dry-run.log" 2>&1; then
      patch --batch --forward --strip=1 < "$file" \
        | tee "$LOGDIR/07-vram.apply.log"
    else
      cat "$LOGDIR/07-vram.dry-run.log"
      echo "==> Raw aggregate does not match; applying deterministic semantic port"
      python3 "$ROOT/scripts/port-vram-cgroup.py" "$KERNELDIR" \
        | tee "$LOGDIR/07-vram-semantic-port.log"
    fi
  fi

  # Preserve reference balance if the upstream aggregate applied directly.
  # The deterministic port already includes the same correction.
  python3 - "$KERNELDIR/kernel/cgroup/dmem.c" <<'VRAMPY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "dmem_cgroup_get_common_ancestor" not in text:
    raise SystemExit("VRAM dmem common-ancestor helper is missing")
if "css_put(ancestor_css);" not in text:
    old_decl = "{\n\tstruct cgroup *ancestor_cgroup;\n\tstruct cgroup_subsys_state *ancestor_css;\n\n\tif (!a || !b)\n"
    new_decl = "{\n\tstruct dmem_cgroup_pool_state *pool;\n\tstruct cgroup *ancestor_cgroup;\n\tstruct cgroup_subsys_state *ancestor_css;\n\n\tif (!a || !b)\n"
    old_return = "\treturn get_cg_pool_unlocked(css_to_dmemcs(ancestor_css), a->region);\n}"
    new_return = "\tpool = get_cg_pool_unlocked(css_to_dmemcs(ancestor_css), a->region);\n\tif (IS_ERR(pool)) {\n\t\tcss_put(ancestor_css);\n\t\treturn NULL;\n\t}\n\n\treturn pool;\n}"
    if text.count(old_decl) != 1 or text.count(old_return) != 1:
        raise SystemExit("VRAM direct-patch reference cleanup anchors are missing")
    text = text.replace(old_decl, new_decl, 1).replace(old_return, new_return, 1)
    path.write_text(text, encoding="utf-8")
VRAMPY

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check -- drivers/gpu/drm/ttm include/drm/ttm \
    include/linux/cgroup.h include/linux/cgroup_dmem.h kernel/cgroup/dmem.c \
    | tee "$LOGDIR/07-vram-diff-check.log"
  grep -Fq 'struct ttm_bo_alloc_state' drivers/gpu/drm/ttm/ttm_bo.c
  grep -Fq 'ttm_resource_try_charge' drivers/gpu/drm/ttm/ttm_resource.c
  grep -Fq 'dmem_cgroup_below_min' include/linux/cgroup_dmem.h
  grep -Fq 'dmem_cgroup_get_common_ancestor' kernel/cgroup/dmem.c
  grep -Fq 'css_put(ancestor_css)' kernel/cgroup/dmem.c
  echo "==> VRAM cgroup/TTM policy applied successfully"
}

apply_infinity_patch() {
'''
)

replace_once(
    'fetch_infinity_patch\n',
    'fetch_infinity_patch\nfetch_vram_patch\n'
)

replace_once(
    'apply_infinity_patch "$INFINITY_PATCH"\n',
    'apply_infinity_patch "$INFINITY_PATCH"\napply_vram_patch "$VRAM_PATCH"\n'
)

replace_once(
    'scripts/config --enable LRU_MARIE\n',
    '''scripts/config --enable CGROUPS
scripts/config --enable CGROUP_DMEM
scripts/config --enable LRU_MARIE
'''
)

replace_once(
    'assert_config "CONFIG_LRU_MARIE=y"\n',
    '''assert_config "CONFIG_CGROUP_DMEM=y"
assert_config "CONFIG_LRU_MARIE=y"
'''
)

replace_once(
    'if [[ "$MODE" == "package" ]]; then\n',
    '''"$ROOT/scripts/build-vram-package.sh" "$MODE"

if [[ "$MODE" == "package" ]]; then
'''
)
"""

    anchor = 'output.write_text(source, encoding="utf-8")\n'
    wrapper = replace_once(wrapper, anchor, injection + "\n" + anchor, "VRAM wrapper injection")
    path.write_text(wrapper, encoding="utf-8")
    print("Injected VRAM/DMEM kernel and userspace integration")


if __name__ == "__main__":
    main()
