#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

resolver = Path("scripts/resolve-patch-sources.py")
text = resolver.read_text(encoding="utf-8")
new_distance = '''def kernel_distance(target: KernelVersion, kernel: KernelVersion) -> int:
    left = target.parts + (0,) * (3 - len(target.parts))
    right = kernel.parts + (0,) * (3 - len(kernel.parts))
    # Compare a monotonic kernel-version ordinal. Component-wise absolute
    # differences incorrectly rank 6.18 closer to 7.1 than 6.19.
    left_ordinal = left[0] * 1_000_000 + left[1] * 1_000 + left[2]
    right_ordinal = right[0] * 1_000_000 + right[1] * 1_000 + right[2]
    return abs(left_ordinal - right_ordinal)


'''
text, count = re.subn(
    r"def kernel_distance\(.*?(?=def compatibility_score\()",
    new_distance,
    text,
    count=1,
    flags=re.DOTALL,
)
if count != 1:
    raise SystemExit(f"kernel_distance function matches: {count}")

new_candidate = '''def candidate_score(path: str, kernel: KernelVersion, version_pattern: str | None) -> tuple[Any, ...]:
    target = extract_kernel_target(path)
    compat_rank, distance_rank = compatibility_score(target, kernel)
    target_parts = target.parts if target else ()
    channel_rank = 2 if "/stable/" in f"/{path}" else 1 if "/testing/" in f"/{path}" else 0
    version = project_version(path, version_pattern)
    # Prefer the newer kernel target when distance is tied (Linux 7.2 over 7.0
    # for a Linux 7.1 build), then the newest project version.
    return compat_rank, distance_rank, target_parts, version_key(version), channel_rank, path


'''
text, count = re.subn(
    r"def candidate_score\(.*?(?=def match_paths\()",
    new_candidate,
    text,
    count=1,
    flags=re.DOTALL,
)
if count != 1:
    raise SystemExit(f"candidate_score function matches: {count}")
resolver.write_text(text, encoding="utf-8")

bore_test = Path("tests/test_bore_liquorix_port.py")
text = bore_test.read_text(encoding="utf-8")
old_testing = '"patches/testing/0001-linux{series}-rc*-bore-*.patch",'
new_testing = '"patches/testing/0001-linux{series}*-bore-*.patch",'
old_stable = '"patches/stable/linux-{series}-bore/0001-linux{series}-rc*-bore-*.patch",'
new_stable = '"patches/stable/linux-{series}-bore/0001-linux{series}*-bore-*.patch",'
if text.count(old_testing) != 1 or text.count(old_stable) != 1:
    raise SystemExit("BORE contract anchors are missing")
text = text.replace(old_testing, new_testing, 1).replace(old_stable, new_stable, 1)
bore_test.write_text(text, encoding="utf-8")

resolver_test = Path("tests/test_dynamic_patch_resolver.py")
text = resolver_test.read_text(encoding="utf-8")
old_regex = '"project_version_regex": r"demo-v([0-9.]+)",'
new_regex = '"project_version_regex": r"demo-v([0-9]+(?:\\.[0-9]+)*)",'
if text.count(old_regex) != 1:
    raise SystemExit(f"resolver test version regex anchors: {text.count(old_regex)}")
resolver_test.write_text(text.replace(old_regex, new_regex, 1), encoding="utf-8")

reflex = Path("scripts/apply-reflex-core.py")
text = reflex.read_text(encoding="utf-8")
text = re.sub(
    r"  # source implements cpufreq_default_governor\(\) behind that symbol\. If the selected patch does not add the symbol to the default-governor\n\s+# choice, complete\n  # that integration here before olddefconfig\.",
    "  # source implements cpufreq_default_governor() behind that symbol. If the\n"
    "  # selected patch does not add the default-governor choice, complete that\n"
    "  # integration here before olddefconfig.",
    text,
    count=1,
)
reflex.write_text(text, encoding="utf-8")
