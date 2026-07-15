#!/usr/bin/env python3
"""Resolve the two expected BORE 6.8.0-rc1 hunks on Liquorix 7.1.3-lqx1."""

from pathlib import Path
import sys


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one compatibility target, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-bore-liquorix.py /path/to/linux")

    tree = Path(sys.argv[1])
    fair = tree / "kernel/sched/fair.c"
    debug = tree / "kernel/sched/debug.c"

    replace_once(
        fair,
        "unsigned int sysctl_sched_tunable_scaling = SCHED_TUNABLESCALING_LOG;",
        """#ifdef CONFIG_SCHED_BORE
unsigned int sysctl_sched_tunable_scaling = SCHED_TUNABLESCALING_NONE;
#else /* !CONFIG_SCHED_BORE */
unsigned int sysctl_sched_tunable_scaling = SCHED_TUNABLESCALING_LOG;
#endif /* CONFIG_SCHED_BORE */""",
    )

    replace_once(
        fair,
        """#ifdef CONFIG_ZEN_INTERACTIVE
unsigned int sysctl_sched_base_slice\t\t\t= 400000ULL;
static unsigned int normalized_sysctl_sched_base_slice\t= 400000ULL;
#else
unsigned int sysctl_sched_base_slice\t\t\t= 700000ULL;
static unsigned int normalized_sysctl_sched_base_slice\t= 700000ULL;
#endif""",
        """#ifdef CONFIG_SCHED_BORE
static const unsigned int nsecs_per_tick = 1000000000ULL / HZ;
unsigned int sysctl_sched_min_base_slice = CONFIG_MIN_BASE_SLICE_NS;
__read_mostly uint sysctl_sched_base_slice = nsecs_per_tick;
#else /* !CONFIG_SCHED_BORE */
#ifdef CONFIG_ZEN_INTERACTIVE
unsigned int sysctl_sched_base_slice\t\t\t= 400000ULL;
static unsigned int normalized_sysctl_sched_base_slice\t= 400000ULL;
#else
unsigned int sysctl_sched_base_slice\t\t\t= 700000ULL;
static unsigned int normalized_sysctl_sched_base_slice\t= 700000ULL;
#endif
#endif /* CONFIG_SCHED_BORE */""",
    )

    replace_once(
        debug,
        '\tdebugfs_create_u32("base_slice_ns", 0644, debugfs_sched, &sysctl_sched_base_slice);',
        """#ifdef CONFIG_SCHED_BORE
\tdebugfs_create_file("min_base_slice_ns", 0644, debugfs_sched, NULL,
\t\t\t    &sched_min_base_slice_fops);
\tdebugfs_create_u32("base_slice_ns", 0444, debugfs_sched,
\t\t\t   &sysctl_sched_base_slice);
#else /* !CONFIG_SCHED_BORE */
\tdebugfs_create_u32("base_slice_ns", 0644, debugfs_sched,
\t\t\t   &sysctl_sched_base_slice);
#endif /* CONFIG_SCHED_BORE */""",
    )

    replace_once(
        debug,
        '\tdebugfs_create_file("tunable_scaling", 0644, debugfs_sched, NULL, &sched_scaling_fops);',
        """#if !defined(CONFIG_SCHED_BORE)
\tdebugfs_create_file("tunable_scaling", 0644, debugfs_sched, NULL,
\t\t\t    &sched_scaling_fops);
#endif /* !CONFIG_SCHED_BORE */""",
    )

    print("Applied Liquorix compatibility for BORE debug and base-slice hunks.")


if __name__ == "__main__":
    main()
