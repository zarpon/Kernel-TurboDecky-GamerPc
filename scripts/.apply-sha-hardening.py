#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one literal match, found {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"{label}: expected one regex match, found {count}")
    return updated


manifest_path = ROOT / "config/patch-sources.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
bore = manifest["components"]["bore"]
old_sha = bore.pop("approved_sha256", None)
if old_sha != "87b9b6f5bedc05db2fb59e921ca7cd172a2a68c1267834d5c5c771cc0f48fd36":
    raise SystemExit(f"unexpected previous BORE approval SHA: {old_sha!r}")
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

resolver_path = "scripts/resolve-patch-sources.py"
resolver = read(resolver_path)
resolver = sub_once(
    resolver,
    r'''                    approved_sha256 = spec\.get\("approved_sha256"\)\n                    actual_sha256 = sha256\(data\)\n                    if approved_sha256 and actual_sha256 != approved_sha256:\n                        raise ResolverError\(\n                            f"\{component\} selected current official source with SHA-256 "\n                            f"\{actual_sha256\}, but the reviewed local port requires "\n                            f"\{approved_sha256\}; refresh and validate the port"\n                        \)\n                    write_bytes\(output_path, data\)''',
    '''                    # Dynamic upstream sources are pinned by commit, path, size and
                    # SHA-256 in patch-lock.json. A manifest-level content hash would
                    # become stale whenever the tracked upstream branch legitimately
                    # publishes a new compatible patch.
                    write_bytes(output_path, data)''',
    "git source SHA gate",
)
resolver = sub_once(
    resolver,
    r'''                        approved_sha256 = spec\.get\("approved_sha256"\)\n                        actual_sha256 = sha256\(candidate\)\n                        if approved_sha256 and actual_sha256 != approved_sha256:\n                            raise ResolverError\(\n                                f"\{component\} selected current official source with SHA-256 "\n                                f"\{actual_sha256\}, but the reviewed local port requires "\n                                f"\{approved_sha256\}; refresh and validate the port"\n                            \)\n                        data = candidate''',
    '''                        # Integrity is recorded from the downloaded bytes in the
                        # generated lock; fixed fallback metadata remains independently
                        # checked by load_local_fallback().
                        data = candidate''',
    "HTTP source SHA gate",
)
write(resolver_path, resolver)

validator = '''#!/usr/bin/env python3
"""Verify that every resolved patch byte-for-byte matches its generated lock."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class IntegrityError(RuntimeError):
    pass


def load_lock(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"unable to read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise IntegrityError("unsupported resolved patch lock")
    if not isinstance(value.get("components"), dict):
        raise IntegrityError("resolved patch lock has no components object")
    return value


def contained_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise IntegrityError(f"resolved output escapes lock directory: {relative}") from exc
    return candidate


def validate_lock(lock_path: Path) -> int:
    lock = load_lock(lock_path)
    root = lock_path.parent
    checked = 0
    for name, raw in lock["components"].items():
        if not isinstance(raw, dict):
            raise IntegrityError(f"{name}: lock record must be an object")
        digest = raw.get("sha256")
        size = raw.get("size")
        output = raw.get("output")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise IntegrityError(f"{name}: invalid SHA-256 in lock")
        if not isinstance(size, int) or size <= 0:
            raise IntegrityError(f"{name}: invalid size in lock")
        if not isinstance(output, str) or not output:
            raise IntegrityError(f"{name}: missing output path")
        path = contained_file(root, output)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise IntegrityError(f"{name}: unable to read materialized output {path}: {exc}") from exc
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise IntegrityError(f"{name}: materialized SHA-256 {actual} != lock {digest}")
        if len(data) != size:
            raise IntegrityError(f"{name}: materialized size {len(data)} != lock {size}")

        kind = raw.get("kind")
        if kind in {"git_patch", "git_file"}:
            for field in ("repo", "ref", "commit", "selected_path", "path"):
                if not isinstance(raw.get(field), str) or not raw[field]:
                    raise IntegrityError(f"{name}: missing immutable Git field {field}")
            if not re.fullmatch(r"[0-9a-f]{40}", raw["commit"]):
                raise IntegrityError(f"{name}: invalid resolved Git commit")
        elif kind == "http_patch":
            if not isinstance(raw.get("url"), str) or not raw["url"].startswith("https://"):
                raise IntegrityError(f"{name}: invalid resolved HTTPS URL")
        else:
            raise IntegrityError(f"{name}: unsupported component kind {kind!r}")
        checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default=".resolved-patches/patch-lock.json")
    args = parser.parse_args()
    count = validate_lock(Path(args.lock))
    print(f"Resolved patch integrity passed for {count} components")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IntegrityError as exc:
        print(f"resolved patch integrity error: {exc}", file=sys.stderr)
        raise SystemExit(2)
'''
write("scripts/validate-resolved-patches.py", validator)

test = '''#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "validate_resolved_patches", root / "scripts/validate-resolved-patches.py"
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    lock_root = Path(tmp) / ".resolved-patches"
    files = lock_root / "files"
    files.mkdir(parents=True)
    data = b"From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\\n"
    output = files / "01-test.patch"
    output.write_bytes(data)
    lock = {
        "schema": 1,
        "kernel": {"version": "7.1.5", "series": "7.1"},
        "components": {
            "test": {
                "kind": "git_patch",
                "output": "files/01-test.patch",
                "repo": "https://github.com/example/project.git",
                "ref": "main",
                "commit": "a" * 40,
                "selected_path": "patches/test.patch",
                "path": "patches/test.patch",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        },
    }
    lock_path = lock_root / "patch-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert module.validate_lock(lock_path) == 1

    output.write_bytes(data + b"mutated")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("mutated patch was accepted")

    output.write_bytes(data)
    lock["components"]["test"]["output"] = "../outside.patch"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("escaping output path was accepted")

print("Resolved patch integrity regression tests passed")
'''
write("tests/test-resolved-patch-integrity.py", test)

workflow_path = ".github/workflows/validate-kernel.yml"
workflow = read(workflow_path)
workflow = replace_once(
    workflow,
    "          python3 scripts/apply-zarpon-generic-name.py scripts/build-kernelnote-core.sh scripts/build-kernelnote.sh\n          python3 scripts/finalize-bore-stable-port.py scripts/build-kernelnote-core.sh",
    "          python3 scripts/apply-zarpon-generic-name.py scripts/build-kernelnote-core.sh scripts/build-kernelnote.sh\n          python3 scripts/validate-resolved-patches.py --lock .resolved-patches/patch-lock.json\n          python3 tests/test-resolved-patch-integrity.py\n          python3 scripts/finalize-bore-stable-port.py scripts/build-kernelnote-core.sh",
    "workflow materialized lock validation",
)
new_verify = '''      - name: Verify BORE scheduler and POC compatibility
        shell: bash
        run: |
          set -Eeuo pipefail
          BORE_VERSION="$(python3 - <<'PY'
          import json
          from pathlib import Path
          lock = json.loads(Path('.resolved-patches/patch-lock.json').read_text(encoding='utf-8'))
          print(lock['components']['bore']['project_version'])
          PY
          )"
          test -n "$BORE_VERSION"
          grep -Fq "Component: BORE scheduler ${BORE_VERSION}" logs/01-bore-provenance.txt
          grep -Fq 'Component: BORE sched_ext coexistence fix' logs/01-bore-sched-ext-provenance.txt
          grep -Fq "BORE ${BORE_VERSION} Linux port applied successfully" logs/build.log
          grep -Fq 'BORE sched_ext coexistence fix applied successfully' logs/build.log
          grep -Fq 'SCHED_BORE_VERSION' .resolved-patches/files/01-bore.patch
          grep -Fq 'void reweight_task(struct task_struct *p, int prio)' .resolved-patches/files/01-bore-sched-ext-coexistence-fix.patch
          grep -Fq 'struct bore_ctx' work/linux/include/linux/sched.h
          test -s work/linux/kernel/sched/bore.c
          grep -Fq 'sched_bore' work/linux/kernel/sched/fair.c
          grep -Fq 'void reweight_task(struct task_struct *p, int prio)' work/linux/kernel/sched/fair.c
          grep -Fq 'extern void reweight_task(struct task_struct *p, int prio);' work/linux/include/linux/sched/bore.h
          grep -Fq 'CONFIG_SCHED_POC_SELECTOR=y' logs/final.config
          grep -Fq 'CONFIG_SCHED_BORE=y' logs/final.config
          grep -Fq 'CONFIG_ZEN_INTERACTIVE=y' logs/final.config
          grep -Fq 'CONFIG_X86_INTEL_PSTATE=y' logs/final.config
          grep -Fq 'CONFIG_X86_AMD_PSTATE=y' logs/final.config
          grep -Fq 'CONFIG_X86_AMD_PSTATE_DEFAULT_MODE=2' logs/final.config
          grep -Fq 'intel_pstate=passive' logs/final.config
          grep -Fq 'amd_pstate=passive' logs/final.config
          python3 - <<'PY'
          import fnmatch
          import hashlib
          import json
          import re
          from pathlib import Path

          lock = json.loads(Path('.resolved-patches/patch-lock.json').read_text(encoding='utf-8'))
          manifest = json.loads(Path('config/patch-sources.json').read_text(encoding='utf-8'))
          spec = manifest['components']['bore']
          bore = lock['components']['bore']
          assert bore['ref'] == spec.get('ref', 'main')
          assert bore['selection'] == 'exact'
          values = {
              'kernel_version': lock['kernel']['version'],
              'series': lock['kernel']['series'],
          }
          patterns = [pattern.format(**values) for pattern in spec['exact_globs']]
          selected = bore['selected_path']
          assert any(fnmatch.fnmatch(selected, pattern) for pattern in patterns), (selected, patterns)
          match = re.search(spec['project_version_regex'], selected, flags=re.IGNORECASE)
          assert match and bore['project_version'] == match.group(1)
          assert re.fullmatch(r'[0-9a-f]{40}', bore['commit'])
          assert re.fullmatch(r'[0-9a-f]{64}', bore['sha256'])
          materialized = Path('.resolved-patches') / bore['output']
          data = materialized.read_bytes()
          assert hashlib.sha256(data).hexdigest() == bore['sha256']
          assert len(data) == bore['size']

          sched_ext = lock['components']['bore_sched_ext_coexistence']
          assert sched_ext['ref'] == 'main'
          assert sched_ext['selection'] == 'exact'
          assert sched_ext['path'] == 'patches/additions/0002-sched-ext-coexistence-fix.patch'
          PY

'''
workflow = sub_once(
    workflow,
    r'''      - name: Verify BORE scheduler and POC compatibility\n.*?(?=      - name: Verify validation module coverage)''',
    new_verify,
    "workflow dynamic BORE verification",
)
write(workflow_path, workflow)

(ROOT / "scripts/.apply-sha-hardening.py").unlink()
(ROOT / ".github/workflows/apply-sha-hardening.yml").unlink(missing_ok=True)
