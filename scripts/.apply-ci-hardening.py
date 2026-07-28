#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / ".github/workflows/validate-kernel.yml"
text = PATH.read_text(encoding="utf-8")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


text = replace_once(
    text,
    "          python3 scripts/apply-zarpon-generic-name.py scripts/build-kernelnote-core.sh scripts/build-kernelnote.sh\n          python3 scripts/finalize-bore-stable-port.py scripts/build-kernelnote-core.sh",
    "          python3 scripts/apply-zarpon-generic-name.py scripts/build-kernelnote-core.sh scripts/build-kernelnote.sh\n          python3 scripts/validate-resolved-patches.py --lock .resolved-patches/patch-lock.json\n          python3 tests/test-resolved-patch-integrity.py\n          python3 scripts/finalize-bore-stable-port.py scripts/build-kernelnote-core.sh",
    "resolved lock validation",
)

new_block = '''      - name: Verify BORE scheduler and POC compatibility
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
pattern = r"      - name: Verify BORE scheduler and POC compatibility\n.*?(?=      - name: Verify validation module coverage)"
text, count = re.subn(pattern, lambda _match: new_block, text, count=1, flags=re.DOTALL)
if count != 1:
    raise SystemExit(f"BORE workflow block: expected one match, found {count}")

PATH.write_text(text, encoding="utf-8")
(ROOT / "scripts/.apply-ci-hardening.py").unlink()
(ROOT / ".github/workflows/apply-sha-hardening.yml").unlink()
