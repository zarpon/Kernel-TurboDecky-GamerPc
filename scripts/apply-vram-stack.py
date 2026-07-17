#!/usr/bin/env python3
"""Inject the pinned TTM/dmem VRAM protection stack into the kernel build."""

from __future__ import annotations

from pathlib import Path
import sys


DIAGNOSTIC = Path("logs/vram-integrator.txt")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    DIAGNOSTIC.parent.mkdir(parents=True, exist_ok=True)
    with DIAGNOSTIC.open("a", encoding="utf-8") as stream:
        stream.write(f"{label}: {count}\n")
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch_core(path: Path) -> None:
    DIAGNOSTIC.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC.write_text(f"core: {path}\n", encoding="utf-8")
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        'INFINITY_PATCH="$PATCHDIR/0001-infinity-scheduler.patch"\n',
        '''INFINITY_PATCH="$PATCHDIR/0001-infinity-scheduler.patch"

# Pixelcluster's six TTM/dmem protection fixes, carried by CachyOS as one
# reproducible patch. The commit is pinned and only the exact patch blob is read.
CGROUP_VRAM_REPO="https://github.com/CachyOS/kernel-patches.git"
CGROUP_VRAM_COMMIT="ea739d734ec179864b21446856315bc49f7c52fa"
CGROUP_VRAM_PATCH_PATH="7.0/misc/0001-cgroup-vram.patch"
CGROUP_VRAM_DIR="$WORKDIR/cachyos-kernel-patches"
CGROUP_VRAM_PATCH="$PATCHDIR/0007-cgroup-vram-protection.patch"
''',
        "VRAM source variables",
    )

    source = replace_once(
        source,
        'normalize_changed_whitespace() {\n',
        r'''fetch_cgroup_vram_patch() {
  echo "==> Fetching pinned Pixelcluster TTM/dmem VRAM protection patch"
  rm -rf "$CGROUP_VRAM_DIR"
  git init --quiet "$CGROUP_VRAM_DIR"
  git -C "$CGROUP_VRAM_DIR" remote add origin "$CGROUP_VRAM_REPO"
  git -C "$CGROUP_VRAM_DIR" config remote.origin.promisor true
  git -C "$CGROUP_VRAM_DIR" config remote.origin.partialclonefilter blob:none
  git -C "$CGROUP_VRAM_DIR" fetch --no-tags --depth=1 --filter=blob:none \
    origin "$CGROUP_VRAM_COMMIT" 2>&1 | tee "$LOGDIR/07-cgroup-vram-fetch.log"

  git -C "$CGROUP_VRAM_DIR" show \
    "FETCH_HEAD:$CGROUP_VRAM_PATCH_PATH" > "$CGROUP_VRAM_PATCH"
  test -s "$CGROUP_VRAM_PATCH"
  grep -Fq 'Subject: [PATCH] cgroup-vram' "$CGROUP_VRAM_PATCH"
  grep -Fq 'struct ttm_bo_alloc_state' "$CGROUP_VRAM_PATCH"
  grep -Fq 'dmem_cgroup_get_common_ancestor' "$CGROUP_VRAM_PATCH"
  grep -Fq 'dmem_cgroup_below_min' "$CGROUP_VRAM_PATCH"
  grep -Fq 'diff --git a/kernel/cgroup/dmem.c b/kernel/cgroup/dmem.c' \
    "$CGROUP_VRAM_PATCH"

  {
    echo "Component: Pixelcluster TTM/dmem VRAM protection"
    echo "Upstream series: six VRAM management fixes"
    echo "Carrier repository: $CGROUP_VRAM_REPO"
    echo "Commit: $CGROUP_VRAM_COMMIT"
    echo "Path: $CGROUP_VRAM_PATCH_PATH"
    echo "SHA256: $(sha256sum "$CGROUP_VRAM_PATCH" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout"
  } | tee "$LOGDIR/07-cgroup-vram-provenance.txt"
}

normalize_changed_whitespace() {
''',
        "VRAM fetch function",
    )

    source = replace_once(
        source,
        'apply_adios_patch() {\n',
        r'''apply_cgroup_vram_patch() {
  local file="$1" status=0

  echo "==> Applying Pixelcluster TTM/dmem VRAM protection"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/07-cgroup-vram.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/07-cgroup-vram.apply.log"
  else
    cat "$LOGDIR/07-cgroup-vram.dry-run.log"
    echo "==> Retrying VRAM protection port with controlled fuzz <= 3"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/07-cgroup-vram.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/07-cgroup-vram.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      {
        echo "==> Unresolved TTM/dmem VRAM protection rejects"
        find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
        echo
        while IFS= read -r reject; do
          echo "### ${reject#$KERNELDIR/}"
          cat "$reject"
        done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
      } | tee "$LOGDIR/07-cgroup-vram-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check -- \
    drivers/gpu/drm/ttm/ttm_bo.c \
    drivers/gpu/drm/ttm/ttm_resource.c \
    include/drm/ttm/ttm_resource.h \
    include/linux/cgroup.h \
    include/linux/cgroup_dmem.h \
    kernel/cgroup/dmem.c \
    | tee "$LOGDIR/07-cgroup-vram-diff-check.log"

  grep -Fq 'struct ttm_bo_alloc_state' drivers/gpu/drm/ttm/ttm_bo.c
  grep -Fq 'dmem_cgroup_get_common_ancestor' kernel/cgroup/dmem.c
  grep -Fq 'dmem_cgroup_below_min' include/linux/cgroup_dmem.h
  echo "==> Pixelcluster TTM/dmem VRAM protection applied successfully"
}

apply_adios_patch() {
''',
        "VRAM apply function",
    )

    source = replace_once(
        source,
        'fetch_infinity_patch\n',
        'fetch_infinity_patch\nfetch_cgroup_vram_patch\n',
        "VRAM fetch call",
    )
    source = replace_once(
        source,
        'apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"\n',
        'apply_adios_patch "$PATCHDIR/0003-adios-3.2.0.patch"\napply_cgroup_vram_patch "$CGROUP_VRAM_PATCH"\n',
        "VRAM apply call",
    )
    source = replace_once(
        source,
        'scripts/config --module BLK_DEV_ZRAM\n',
        '''scripts/config --module BLK_DEV_ZRAM
scripts/config --enable CGROUPS
scripts/config --enable CGROUP_DMEM
scripts/config --module DRM_AMDGPU
''',
        "VRAM kernel configuration",
    )
    source = replace_once(
        source,
        'assert_config "CONFIG_LRU_MARIE=y"\n',
        '''assert_config "CONFIG_LRU_MARIE=y"
assert_config "CONFIG_CGROUP_DMEM=y"
assert_config "CONFIG_DRM_AMDGPU=m"
''',
        "VRAM kernel assertions",
    )
    source = replace_once(
        source,
        'echo "==> Latest-stable TurboDecky ThinLTO build completed successfully"\n',
        '''bash "$ROOT/scripts/build-vram-package.sh"
echo "==> Latest-stable TurboDecky ThinLTO build completed successfully"
''',
        "VRAM package build",
    )

    path.write_text(source, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-vram-stack.py scripts/build-kernelnote-core.sh")
    patch_core(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
