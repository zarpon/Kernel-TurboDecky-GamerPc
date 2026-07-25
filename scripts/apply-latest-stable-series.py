#!/usr/bin/env python3
"""Follow the resolved stable series and preserve project compatibility ports."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BORE_VERSION = "6.8.0-rc1"
BORE_BASE_KERNEL = "7.1.4"
BORE_SUPPORTED_KERNELS = {"7.1.4", "7.1.5"}
BORE_BASE_PATCH = ROOT / "patches/bore/7.1.4-bore-6.8.0-rc1.patch"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}"
        )
    return text.replace(old, new, 1)


def adapt_bore_text(text: str, kernel_version: str) -> str:
    """Return the reviewed BORE port adjusted for a supported stable kernel.

    Linux 7.1.5 removed util_est_update() from dequeue_task_fair() and warns
    against referencing the task after dequeue_entities(DEQUEUE_DELAYED). The
    BORE burst update is therefore placed before dequeue_entities() using the
    new stable context. No fuzzy patching is introduced.
    """

    if kernel_version not in BORE_SUPPORTED_KERNELS:
        supported = ", ".join(sorted(BORE_SUPPORTED_KERNELS))
        raise SystemExit(
            f"no reviewed BORE {BORE_VERSION} port for Linux {kernel_version}; "
            f"supported: {supported}"
        )
    if kernel_version == BORE_BASE_KERNEL:
        return text

    text = replace_once(
        text,
        "Subject: [PATCH] sched: port BORE 6.8.0-rc1 to Linux 7.1.4",
        f"Subject: [PATCH] sched: port BORE 6.8.0-rc1 to Linux {kernel_version}",
        "BORE subject",
    )
    text = replace_once(
        text,
        "Port of the official BORE 7.1 test patch to Linux 7.1.4.",
        f"Port of the official BORE 7.1 test patch to Linux {kernel_version}.",
        "BORE description",
    )

    header = re.compile(
        r"^@@[^\n]*@@ static bool dequeue_task_fair\(struct rq \*rq, "
        r"struct task_struct \*p, int flags\)\n",
        re.MULTILINE,
    )
    match = header.search(text)
    if not match:
        raise SystemExit("BORE dequeue_task_fair hunk was not found")

    following = re.search(
        r"^(?:@@ |diff --git )", text[match.end() :], re.MULTILINE
    )
    end = match.end() + (
        following.start() if following else len(text[match.end() :])
    )
    old_hunk = text[match.start() : end]
    required = (
        "util_est_update(&rq->cfs, p, flags & DEQUEUE_SLEEP);",
        "restart_burst_bore(p);",
        "if (dequeue_entities(rq, &p->se, flags) < 0)",
    )
    missing = [token for token in required if token not in old_hunk]
    if missing:
        raise SystemExit(
            f"unexpected BORE dequeue_task_fair hunk layout; missing {missing}"
        )

    new_hunk = """@@ -7427,6 +7523,20 @@ static bool dequeue_task_fair(struct rq *rq, struct task_struct *p, int flags)
 \tif (!p->se.sched_delayed)
 \t\tutil_est_dequeue(&rq->cfs, p);
 
+#ifdef CONFIG_SCHED_BORE
+\t{
+\t\tstruct cfs_rq *cfs_rq = cfs_rq_of(&p->se);
+\t\tstruct sched_entity *se = &p->se;
+
+\t\tif ((flags & DEQUEUE_SLEEP) && entity_is_task(se)) {
+\t\t\tif (cfs_rq->curr == se)
+\t\t\t\tupdate_curr(cfs_rq);
+\t\t\trestart_burst_bore(p);
+\t\t}
+\t}
+#endif /* CONFIG_SCHED_BORE */
+
 \tif (dequeue_entities(rq, &p->se, flags) < 0)
 \t\treturn false;
 
"""
    return text[: match.start()] + new_hunk + text[end:]


def materialize_bore_port(kernel_version: str) -> Path:
    source = BORE_BASE_PATCH.read_text(encoding="utf-8")
    adapted = adapt_bore_text(source, kernel_version)
    destination = (
        BORE_BASE_PATCH.parent
        / f".resolved-{kernel_version}-bore-{BORE_VERSION}.patch"
    )
    destination.write_text(adapted, encoding="utf-8")
    return destination


def patch_core(path: Path, bore_patch: Path, kernel_version: str) -> None:
    source = path.read_text(encoding="utf-8")
    replacements = {
        "linux-tkg-patches/7.1/": "linux-tkg-patches/${KERNEL_SERIES}/",
        "0007-v7.1-fsync1_via_futex_waitv.patch": "0007-v${KERNEL_SERIES}-fsync1_via_futex_waitv.patch",
        "genpatches/trunk/7.1/": "genpatches/trunk/${KERNEL_SERIES}/",
        "kernel-patches/refs/heads/master/7.1/": "kernel-patches/refs/heads/master/${KERNEL_SERIES}/",
        "Compatibility policy: Linux 7.1-specific or upstream-integrated source preferred":
            "Compatibility policy: Linux $KERNEL_SERIES-specific or upstream-integrated source preferred",
        "Compatibility policy: no usable Linux 7.1-specific source found; controlled port source selected":
            "Compatibility policy: no usable Linux $KERNEL_SERIES-specific source found; controlled port source selected",
        "Resolving requested patch series, preferring Linux 7.1 revisions":
            "Resolving requested patch series, preferring Linux $KERNEL_SERIES revisions",
        "already integrated in Linux 7.1.3 or an earlier patch":
            "already integrated in Linux $KERNEL_VERSION or an earlier patch",
        "if curl --fail --location --retry 3 --retry-all-errors --retry-delay 2 \\\n":
            "if curl --user-agent 'TurboDecky-GamerPc-CI/1.0 (+https://github.com/zarpon/Kernel-TurboDecky-GamerPc)' --fail --location \\\n        --retry 3 --retry-all-errors --retry-delay 2 \\\n",
    }

    for old, new in replacements.items():
        if old not in source:
            raise SystemExit(f"latest-stable patch-series anchor missing: {old!r}")
        source = source.replace(old, new)

    relative_bore = bore_patch.relative_to(ROOT).as_posix()
    source = replace_once(
        source,
        'BORE_PATCH="$ROOT/patches/bore/7.1.4-bore-6.8.0-rc1.patch"',
        f'BORE_PATCH="$ROOT/{relative_bore}"',
        "resolved BORE patch path",
    )
    source = replace_once(
        source,
        "grep -Fq 'sched: port BORE 6.8.0-rc1 to Linux 7.1.4' \"$BORE_PATCH\"",
        f"grep -Fq 'sched: port BORE 6.8.0-rc1 to Linux {kernel_version}' \"$BORE_PATCH\"",
        "resolved BORE subject assertion",
    )
    source = source.replace(
        "Applying the reviewed BORE 6.8.0-rc1 Linux 7.1.4 port",
        f"Applying the reviewed BORE 6.8.0-rc1 Linux {kernel_version} port",
    )
    source = source.replace(
        "BORE 6.8.0-rc1 for Linux 7.1.4",
        f"BORE 6.8.0-rc1 for Linux {kernel_version}",
    )
    path.write_text(source, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''  "cpuidle.governor=nap"
)
''',
        '''  "cpuidle.governor=nap"
  "kvm.enable_virt_at_load=0"
)
''',
        "VirtualBox/KVM command line",
    )
    source = replace_once(
        source,
        'scripts/config --enable CPU_IDLE_GOV_NAP\n',
        '''scripts/config --enable CPU_IDLE_GOV_NAP
# VirtualBox host drivers are external modules. Preserve the module loader,
# symbol metadata and host-network devices they require.
scripts/config --enable MODULES
scripts/config --enable MODULE_UNLOAD
scripts/config --enable MODULE_FORCE_UNLOAD
scripts/config --enable KALLSYMS
scripts/config --enable KALLSYMS_ALL
scripts/config --enable VIRTUALIZATION
scripts/config --module KVM
scripts/config --module KVM_INTEL
scripts/config --module KVM_AMD
scripts/config --module TUN
scripts/config --module BRIDGE
scripts/config --enable NETFILTER
''',
        "VirtualBox host Kconfig",
    )
    source = replace_once(
        source,
        'assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"\n',
        '''assert_config "CONFIG_CPU_IDLE_GOV_NAP=y"
assert_config "CONFIG_MODULES=y"
assert_config "CONFIG_MODULE_UNLOAD=y"
assert_config "CONFIG_MODULE_FORCE_UNLOAD=y"
assert_config "CONFIG_KALLSYMS=y"
assert_config "CONFIG_KALLSYMS_ALL=y"
assert_config "CONFIG_VIRTUALIZATION=y"
assert_config "CONFIG_KVM=m"
assert_config "CONFIG_KVM_INTEL=m"
assert_config "CONFIG_KVM_AMD=m"
assert_config "CONFIG_TUN=m"
assert_config "CONFIG_BRIDGE=m"
assert_config "CONFIG_NETFILTER=y"
''',
        "VirtualBox host Kconfig assertions",
    )
    source = replace_once(
        source,
        'assert_cmdline_token "cpuidle.governor=nap"\n',
        '''assert_cmdline_token "cpuidle.governor=nap"
assert_cmdline_token "kvm.enable_virt_at_load=0"
''',
        "VirtualBox/KVM command-line assertion",
    )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: apply-latest-stable-series.py <generated-core-script>"
        )

    kernel_version = os.environ.get("KERNEL_VERSION", BORE_BASE_KERNEL)
    bore_patch = materialize_bore_port(kernel_version)
    core = Path(sys.argv[1])
    patch_core(core, bore_patch, kernel_version)
    patch_wrapper(core.with_name("build-kernelnote.sh"))


if __name__ == "__main__":
    main()
