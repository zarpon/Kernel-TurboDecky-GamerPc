#!/usr/bin/env python3
"""Resolve the expected ADIOS default-elevator hunk on Liquorix 7.1.3."""

from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-adios-liquorix.py /path/to/linux")

    path = Path(sys.argv[1]) / "block/elevator.c"
    text = path.read_text(encoding="utf-8")

    marker = "#ifdef CONFIG_MQ_IOSCHED_DEFAULT_ADIOS"
    start = text.find(marker)
    if start < 0:
        raise SystemExit("ADIOS default-elevator start marker not found")

    end_marker = "\n\tctx.type = elevator_find_get(ctx.name);"
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit("ADIOS default-elevator end marker not found")

    replacement = """#ifdef CONFIG_MQ_IOSCHED_DEFAULT_ADIOS
\tctx.name = "adios";
#else /* !CONFIG_MQ_IOSCHED_DEFAULT_ADIOS */
\t/* Preserve Liquorix defaults when ADIOS is not selected globally. */
\tif (q->nr_hw_queues != 1 && !blk_mq_is_shared_tags(q->tag_set->flags))
#if defined(CONFIG_ZEN_INTERACTIVE) && defined(CONFIG_MQ_IOSCHED_KYBER)
\t\tctx.name = "kyber";
#else
\t\treturn;
#endif
#endif /* CONFIG_MQ_IOSCHED_DEFAULT_ADIOS */
"""

    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
    print("Applied Liquorix compatibility for the ADIOS default elevator.")


if __name__ == "__main__":
    main()
