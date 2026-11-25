#!/usr/bin/env python3
"""Prepare current CAST bytes, trying the unmodified patch before any port.

Only the reviewed mm/folio.c kvm_types.h include-context change is adapted.
Unknown API changes fail git apply --check and require a reviewed port; no
older release or partially applied kernel tree is accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
from pathlib import Path


def check(tree: Path, patch: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['git', '-C', str(tree), 'apply', '--check', str(patch.resolve())],
                          text=True, capture_output=True)



# Latest upstream 0.2.9, immutable 7.3-rc7 variant. The one-off 7.4-rc1
# rebase is never available to another RC, source commit or patch revision.
CAST_74_BASE_SHA256 = "f02187c4c6605ec08e5b128b3e30a2bd881aa7438f0f2934310de4b18632eb23"
LINUX_74_RC1_COMMIT = "6628e7d4c6b25c8d18f1345e3a20d21829aae7e4"


def replace_exactly_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"CAST 7.4-rc1 {label} no longer has the reviewed preimage ({count} occurrences)")
    return text.replace(old, new, 1)


def port_linux74_rc1(source: bytes, tree: Path, patch: str) -> str:
    if hashlib.sha256(source).hexdigest() != CAST_74_BASE_SHA256:
        raise RuntimeError("latest CAST requires a reviewed kernel API port: CAST 7.4-rc1 upstream SHA differs from reviewed v0.2.9")
    commit = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if commit != LINUX_74_RC1_COMMIT:
        raise RuntimeError(f"CAST 7.4-rc1 kernel source SHA changed: {commit}")
    required_tree_markers = {
        "mm/migrate.c": ("folio_migrate_lru_refs(newfolio, folio);",),
        "mm/swap.h": ("void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio);",),
        "mm/page_io.c": (
            "void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio)",
            "bio_associate_blkg_from_folio(bio, bio_first_folio_all(bio));",
            "folio_test_dropbehind(bvec_folio(&sio->bvecs[p]))",
        ),
        "mm/huge_memory.c": ("new_folio->swap.val = folio->swap.val + i;",),
    }
    for file, markers in required_tree_markers.items():
        current = (tree / file).read_text(encoding="utf-8")
        for marker in markers:
            if current.count(marker) != 1:
                raise RuntimeError(f"CAST 7.4-rc1 source preimage changed: {file}: {marker}")

    # Preserve CAST's migration hook after the new upstream helper that
    # copies PG_referenced and LRU refbits.
    patch = replace_exactly_once(patch,
        " \tif (folio_test_referenced(folio))\n"
        " \t\tfolio_set_referenced(newfolio);",
        " \t/* Copy the reference state, including PG_referenced */\n"
        " \tfolio_migrate_lru_refs(newfolio, folio);\n"
        " \n",
        "migrate reference-state API")

    # The huge folio split site is unchanged, but other kernel patch families
    # modify adjacent context. Anchor the CAST copy to the exact two-line
    # swap-slot copy (one occurrence) rather than unrelated page-flag barriers.
    old_huge = (
        "@@ -3757,6 +3758,8 @@ static void __split_folio_to_order(struct folio *folio, int old_order,\n"
        " \n"
        " \t\tif (folio_test_swapcache(folio))\n"
        " \t\t\tnew_folio->swap.val = folio->swap.val + i;\n"
        "+\t\t/* the new folio's reads are the old one's */\n"
        "+\t\tlru_cast_copy(new_folio, folio);\n"
        " \n"
        " \t\t/* Page flags must be visible before we make the page non-compound. */\n"
        " \t\tsmp_wmb();"
    )
    new_huge = (
        "@@ -3757,3 +3758,5 @@ static void __split_folio_to_order(struct folio *folio, int old_order,\n"
        " \t\tif (folio_test_swapcache(folio))\n"
        " \t\t\tnew_folio->swap.val = folio->swap.val + i;\n"
        "+\t\t/* the new folio's reads are the old one's */\n"
        "+\t\tlru_cast_copy(new_folio, folio);\n"
        " \n"
    )
    patch = replace_exactly_once(patch, old_huge, new_huge, "folio split placement")

    # Linux 7.4 changed names and typing of swap IO helpers. Retain the 7.4
    # void __swap_writeout() implementation and give CAST's wrapper its own name.
    substitutions = (
        (" void __swap_writepage(struct swap_io_ctx *ctx, struct folio *folio);",
         " void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio);",
         "swap header declaration"),
        ("+\t\t__swap_writepage(ctx, folio); /* Implies folio_unlock(folio) */",
         "+\t\t__swap_writeout(ctx, folio); /* Implies folio_unlock(folio) */",
         "swap batching backend"),
        ("+static int __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio, bool handoff)",
         "+static int __cast_swap_writeout(struct swap_io_ctx *ctx, struct folio *folio, bool handoff)",
         "CAST swapout wrapper name"),
        ("+\treturn __swap_writeout(ctx, folio, false);",
         "+\treturn __cast_swap_writeout(ctx, folio, false);",
         "normal swapout call"),
        ("+\treturn __swap_writeout(ctx, folio, true);",
         "+\treturn __cast_swap_writeout(ctx, folio, true);",
         "handoff swapout call"),
        (" static struct cgroup_subsys_state *folio_memcg_blkg_css(struct folio *folio)",
         " static struct cgroup_subsys_state *folio_memcg_blkg_css(const struct folio *folio)",
         "memcg read-only argument"),
        (" \tbio_associate_blkg_from_page(bio, bio_first_folio_all(bio));",
         " \tbio_associate_blkg_from_folio(bio, bio_first_folio_all(bio));",
         "bio blkg helper name"),
        (" \t} else {\n-\t\tbio->bi_end_io = end_swap_bio_write;",
         " \t} else {\n"
         " \t\tint p;\n"
         " \n"
         " \t\tfor (p = 0; p < sio->nr_bvecs; p++) {\n"
         " \t\t\tif (folio_test_dropbehind(bvec_folio(&sio->bvecs[p]))) {\n"
         " \t\t\t\tbio_set_flag(bio, BIO_COMPLETE_IN_TASK);\n"
         " \t\t\t\tbreak;\n"
         " \t\t\t}\n"
         " \t\t}\n"
         " \n"
         "-\t\tbio->bi_end_io = end_swap_bio_write;",
         "swap bio dropbehind semantics"),
    )
    for old, new, label in substitutions:
        patch = replace_exactly_once(patch, old, new, label)
    return patch



CAST_735_SHA256 = "0246c40040b6c65d41d3820a9f72d28592b37959f1204cb032e7a8148f2dc90c"
CAST_735_CONTEXTS = (
    ("mm/filemap.c", " \t * re-find the vma and come back and find our hopefully still populated\n \t * page.\n \t */", " \t * With fpin set, the fault lock was already dropped. Otherwise it is\n \t * still held. Release invalidate_lock before dropping either protection.\n \t */"),
    ("mm/rmap.c", " \t\tif (lru_gen_enabled() && !lru_gen_switching() && pvmw.pte) {\n \t\t\tif (lru_gen_look_around(&pvmw, nr))\n \t\t\t\treferenced++;\n+\t\t} else if (lru_cast_enabled() && pvmw.pte) {\n+\t\t\tif (lru_cast_look_around(&pvmw))\n+\t\t\t\treferenced++;\n \t\t} else if (pvmw.pte) {\n \t\t\tif (clear_flush_young_ptes_notify(vma, address, pvmw.pte, nr))\n \t\t\t\treferenced++;", " \t\tif (lru_gen_enabled() && !lru_gen_switching() && pvmw.pte &&\n \t\t    pte_present(pteval)) {\n \t\t\tif (lru_gen_look_around(&pvmw, nr))\n \t\t\t\treferenced++;\n+\t\t} else if (lru_cast_enabled() && pvmw.pte && pte_present(pteval)) {\n+\t\t\tif (lru_cast_look_around(&pvmw))\n+\t\t\t\treferenced++;\n \t\t} else if (pvmw.pte) {\n \t\t\tbool young = false;\n "),
)


def port_linux735(source: bytes, tree: Path, patch: str) -> str:
    if hashlib.sha256(source).hexdigest() != CAST_735_SHA256:
        raise RuntimeError("CAST 7.3.5 upstream SHA differs from reviewed v0.2.11")
    for name, old, new in CAST_735_CONTEXTS:
        # Preserve the stable fault-lock ordering and non-present PTE path.
        preimage = "\n".join(line[1:] for line in new.split("\n") if line.startswith(" "))
        if (tree / name).read_text(encoding="utf-8").count(preimage) != 1:
            raise RuntimeError(f"CAST 7.3.5 source preimage changed: {name}")
        if patch.count(old) != 1:
            raise RuntimeError(f"CAST 7.3.5 patch preimage changed: {name}")
        patch = patch.replace(old, new, 1)
    return patch


# Reviewed CAST 0.3.0 port: official linux7.3-rc7 -> Linux v7.3.6.
# Upstream firelzrd/lru_cast c2aed944f2b7ca9fdf6ab549eccdf5b5f4f64812
# Target gregkh/linux tag v7.3.6 commit 1a0388846138eda9f6eb4258ff227a223afc2f52
CAST_736_SHA256 = "962359849dfbe6a7a67120cbeb2137d583e3d620b3e40f0bf4f4f161fc17010c"
CAST_736_CONTEXTS = (
    ("mm/filemap.c", " \t * re-find the vma and come back and find our hopefully still populated\n \t * page.\n \t */", " \t * With fpin set, the fault lock was already dropped. Otherwise it is\n \t * still held. Release invalidate_lock before dropping either protection.\n \t */"),
    ("mm/rmap.c", " \t\tif (lru_gen_enabled() && !lru_gen_switching() && pvmw.pte) {\n \t\t\tif (lru_gen_look_around(&pvmw, nr))\n \t\t\t\treferenced++;\n+\t\t} else if (lru_cast_enabled() && pvmw.pte) {\n+\t\t\tif (lru_cast_look_around(&pvmw))\n+\t\t\t\treferenced++;\n \t\t} else if (pvmw.pte) {\n \t\t\tif (clear_flush_young_ptes_notify(vma, address, pvmw.pte, nr))\n \t\t\t\treferenced++;\n", " \t\tif (lru_gen_enabled() && !lru_gen_switching() && pvmw.pte &&\n \t\t    pte_present(pteval)) {\n \t\t\tif (lru_gen_look_around(&pvmw, nr))\n \t\t\t\treferenced++;\n+\t\t} else if (lru_cast_enabled() && pvmw.pte && pte_present(pteval)) {\n+\t\t\tif (lru_cast_look_around(&pvmw))\n+\t\t\t\treferenced++;\n \t\t} else if (pvmw.pte) {\n \t\t\tbool young = false;\n"),
)


def port_linux736(source: bytes, tree: Path, patch: str) -> str:
    if hashlib.sha256(source).hexdigest() != CAST_736_SHA256:
        raise RuntimeError("latest CAST requires a reviewed kernel API port: CAST 7.3.6 upstream source SHA differs from reviewed v0.3.0")
    makefile = (tree / "Makefile").read_text(encoding="utf-8")
    for key, number in (("VERSION", 7), ("PATCHLEVEL", 3), ("SUBLEVEL", 6)):
        if not re.search(rf"^{key}\s*=\s*{number}\s*$", makefile, re.MULTILINE):
            raise RuntimeError(f"CAST 7.3.6 source version mismatch: {key}")
    for name, old, new in CAST_736_CONTEXTS:
        target = (tree / name).read_text(encoding="utf-8")
        preimage = "\n".join(line[1:] for line in new.split("\n") if line.startswith(" "))
        if target.count(preimage) != 1:
            raise RuntimeError(f"CAST 7.3.6 source preimage changed: {name}")
        if patch.count(old) != 1:
            raise RuntimeError(f"CAST 7.3.6 official patch preimage changed: {name}")
        patch = patch.replace(old, new, 1)
    return patch


def prepare(source: Path, output: Path, tree: Path) -> str:
    data = source.read_bytes()
    output.write_bytes(data)
    direct = check(tree, output)
    if direct.returncode == 0:
        return 'upstream-unmodified'
    patch = data.decode('utf-8')
    folio_path = tree / 'mm/folio.c'
    folio = folio_path.read_text(encoding='utf-8') if folio_path.is_file() else ''
    # The 7.3 include was added beside buffer_head.h. Older CAST variants
    # have that exact include as the anchor immediately before CAST's include.
    anchor = ' #include <linux/buffer_head.h>\n'
    added = '+#include <linux/lru_cast.h>\n'
    old = anchor + added
    new = anchor + ' #include <linux/kvm_types.h>\n' + added
    sections = re.split(r'(?=^diff --git )', patch, flags=re.M)
    changed = False
    for index, section in enumerate(sections):
        if not section.startswith('diff --git a/mm/folio.c b/mm/folio.c\n'):
            continue
        if '#include <linux/kvm_types.h>' in folio and section.count(old) == 1:
            sections[index] = section.replace(old, new, 1)
            changed = True
        elif '#include <linux/kvm_types.h>' not in folio and section.count(new) == 1:
            sections[index] = section.replace(new, old, 1)
            changed = True
    if changed:
        # Context changed by one line; --recount recalculates hunk lengths.
        output.write_text(''.join(sections), encoding='utf-8', newline='\n')
        result = subprocess.run(['git', '-C', str(tree), 'apply', '--recount', '--check', str(output.resolve())],
                                text=True, capture_output=True)
        if result.returncode == 0:
            return 'ported-folio-include-context'
        detail = result.stderr
    else:
        detail = direct.stderr
    if os.environ.get("KERNEL_VERSION") == "7.3.5" and hashlib.sha256(data).hexdigest() == CAST_735_SHA256:
        try:
            prepared = port_linux735(data, tree, output.read_text(encoding="utf-8"))
            output.write_text(prepared, encoding="utf-8", newline="\n")
            reviewed = subprocess.run(
                ["git", "-C", str(tree), "apply", "--recount", "--check", str(output.resolve())],
                text=True, capture_output=True,
            )
            if reviewed.returncode == 0:
                return "reviewed-locked-cast-7.3.5-v0.2.11"
            detail = reviewed.stderr
        except RuntimeError:
            output.unlink(missing_ok=True)
            raise
    if os.environ.get("KERNEL_VERSION") == "7.3.6":
        try:
            prepared = port_linux736(data, tree, output.read_text(encoding="utf-8"))
            output.write_text(prepared, encoding="utf-8", newline="\n")
            reviewed = subprocess.run(
                ["git", "-C", str(tree), "apply", "--recount", "--check", str(output.resolve())],
                text=True, capture_output=True,
            )
            if reviewed.returncode == 0:
                return "reviewed-locked-cast-7.3.6-v0.3.0"
            detail = reviewed.stderr
        except (RuntimeError, OSError):
            output.unlink(missing_ok=True)
            raise

    if os.environ.get("KERNEL_VERSION") == "7.4-rc1":
        try:
            prepared = port_linux74_rc1(data, tree, output.read_text(encoding="utf-8"))
        except (RuntimeError, subprocess.CalledProcessError):
            output.unlink(missing_ok=True)
            raise
        output.write_text(prepared, encoding="utf-8", newline="\n")
        reviewed = subprocess.run(
            ["git", "-C", str(tree), "apply", "--recount", "--check", str(output.resolve())],
            text=True, capture_output=True,
        )
        if reviewed.returncode == 0:
            return "reviewed-locked-cast-7.4-rc1"
        detail = reviewed.stderr
    output.unlink()
    raise RuntimeError('latest CAST requires a reviewed kernel API port; refusing older release: ' + detail)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('tree', type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error('output must differ from locked upstream source')
    result = prepare(args.source, args.output, args.tree)
    for path in (args.source, args.output):
        print(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}')
    print(f'CAST preparation: {result}')


if __name__ == '__main__':
    main()
