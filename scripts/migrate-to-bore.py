#!/usr/bin/env python3
"""Replace all Infinity scheduler integration with build-locked BORE testing."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path.cwd()
BORE_COMMIT = "16bf5baebbb42cdba393c501ba9c2af5f84e4749"
BORE_PATH = "patches/testing/0001-linux7.1-rc1-bore-6.8.0-rc1.patch"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    return updated


def update_manifest() -> None:
    path = "config/patch-sources.json"
    manifest = json.loads(read(path))
    components = manifest["components"]
    if "infinity" not in components:
        raise RuntimeError("patch manifest is missing the Infinity component")
    components.pop("infinity")
    bore = {
        "kind": "git_patch",
        "repo": "https://github.com/firelzrd/bore-scheduler.git",
        "ref": "main",
        "exact_globs": ["patches/testing/*linux{series}*bore*.patch"],
        "fallback_globs": [],
        "require_exact_series": True,
        "output": "01-bore.patch",
        "project_version_regex": "bore[-_]?v?([0-9]+(?:\\.[0-9]+)+(?:-rc[0-9]+|r[0-9]+)?)",
        "required_markers": [
            "SCHED_BORE_VERSION",
            "CONFIG_SCHED_BORE",
            "kernel/sched/bore.c",
        ],
    }
    manifest["components"] = {"bore": bore, **components}
    write(path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def update_core() -> None:
    path = "scripts/build-kernelnote-core.sh"
    text = read(path)
    bore_vars = f'''# BORE is resolved from the developer's testing tree for the exact Linux 7.1
# series. These defaults document the current upstream revision; the dynamic
# resolver replaces them with the branch-head snapshot locked for each build.
BORE_REPO="https://github.com/firelzrd/bore-scheduler.git"
BORE_COMMIT="{BORE_COMMIT}"
BORE_PATCH_PATH="{BORE_PATH}"
BORE_DIR="$WORKDIR/bore-scheduler"
BORE_PATCH="$PATCHDIR/0001-bore-testing.patch"

'''
    text = regex_once(
        text,
        r"# Correct Infinity scheduler v3 patch for Linux 7\.1\..*?INFINITY_PATCH=.*?\n\n",
        bore_vars,
        "core scheduler variables",
    )
    fetch_bore = r'''fetch_bore_patch() {
  echo "==> Fetching build-locked BORE testing patch for Linux 7.1"
  rm -rf "$BORE_DIR"
  git init --quiet "$BORE_DIR"
  git -C "$BORE_DIR" remote add origin "$BORE_REPO"
  git -C "$BORE_DIR" config remote.origin.promisor true
  git -C "$BORE_DIR" config remote.origin.partialclonefilter blob:none
  git -C "$BORE_DIR" fetch --no-tags --depth=1 --filter=blob:none origin "$BORE_COMMIT" \
    2>&1 | tee "$LOGDIR/01-bore-fetch.log"

  git -C "$BORE_DIR" show "FETCH_HEAD:$BORE_PATCH_PATH" > "$BORE_PATCH"
  test -s "$BORE_PATCH"
  grep -Fq 'diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c' "$BORE_PATCH"
  grep -Fq 'SCHED_BORE_VERSION' "$BORE_PATCH"
  grep -Fq 'config SCHED_BORE' "$BORE_PATCH"

  {
    echo "Component: BORE scheduler testing"
    echo "Repository: $BORE_REPO"
    echo "Commit: $BORE_COMMIT"
    echo "Path: $BORE_PATCH_PATH"
    echo "SHA256: $(sha256sum "$BORE_PATCH" | awk '{print $1}')"
    echo "Acquisition: build-locked local Git snapshot"
  } | tee "$LOGDIR/01-bore-provenance.txt"
}

normalize_changed_whitespace() {'''
    text = regex_once(
        text,
        r"fetch_infinity_patch\(\) \{.*?\n\}\n\nnormalize_changed_whitespace\(\) \{",
        fetch_bore,
        "core BORE fetch function",
    )
    apply_bore = r'''apply_bore_patch() {
  local file="$1" status=0

  echo "==> Applying BORE testing patch on Linux $KERNEL_VERSION"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/01-bore.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/01-bore.apply.log"
  else
    cat "$LOGDIR/01-bore.dry-run.log"
    echo "==> Retrying BORE with controlled port fuzz <= 3"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/01-bore.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/01-bore.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      {
        echo "==> Unresolved BORE port rejects"
        find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
        echo
        while IFS= read -r reject; do
          echo "### ${reject#$KERNELDIR/}"
          cat "$reject"
        done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
      } | tee "$LOGDIR/01-bore-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  git diff --check | tee "$LOGDIR/01-bore-diff-check.log"

  test -s kernel/sched/bore.c
  test -s include/linux/sched/bore.h
  grep -Fq 'struct bore_ctx' include/linux/sched.h
  grep -Fq 'SCHED_BORE_VERSION' include/linux/sched/bore.h
  grep -Fq 'sched_bore' kernel/sched/bore.c
  grep -Fq 'config SCHED_BORE' init/Kconfig
  echo "==> BORE testing patch applied successfully"
}

apply_adios_patch() {'''
    text = regex_once(
        text,
        r"report_infinity_rejects\(\) \{.*?\napply_adios_patch\(\) \{",
        apply_bore,
        "core BORE apply function",
    )
    replacements = {
        "fetch_infinity_patch": "fetch_bore_patch",
        'apply_infinity_patch "$INFINITY_PATCH"': 'apply_bore_patch "$BORE_PATCH"',
        "# Infinity v3 is integrated directly into CFS/EEVDF and the RT class.\n# Liquorix alternative schedulers must remain disabled so Infinity is effective.":
            "# BORE enhances the upstream CFS/EEVDF path. Alternative schedulers\n# remain disabled so BORE is the effective fair-scheduler enhancement.",
        'scripts/config --set-str LOCALVERSION "-kernelnote-lqx-marie-infinity-adios-thinlto"':
            'scripts/config --set-str LOCALVERSION "-kernelnote-lqx-marie-bore-adios-thinlto"',
        "assert_disabled_or_absent SCHED_BORE": 'assert_config "CONFIG_SCHED_BORE=y"',
    }
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f"core replacement missing: {old}")
        text = text.replace(old, new)
    text = replace_once(
        text,
        "scripts/config --disable SCHED_BMQ\nscripts/config --set-val MIN_BASE_SLICE_NS 2000000",
        "scripts/config --disable SCHED_BMQ\nscripts/config --enable SCHED_BORE\nscripts/config --set-val MIN_BASE_SLICE_NS 2000000",
        "core BORE Kconfig",
    )
    if re.search("infi" + "nity", text, flags=re.IGNORECASE):
        raise RuntimeError("core still contains the removed scheduler name")
    write(path, text)


def update_wrapper() -> None:
    path = "scripts/build-kernelnote.sh"
    text = read(path)
    for old, new in (
        ("apply_infinity_patch", "apply_bore_patch"),
        ("INFINITY_PATCH", "BORE_PATCH"),
        ("Liquorix/Infinity", "Liquorix/BORE"),
        ("-kernelnote-lqx-marie-infinity-adios-thinlto", "-kernelnote-lqx-marie-bore-adios-thinlto"),
        ("-kn-marie-infinity-poc-nap-rfx-adios-zir-lto", "-kn-marie-bore-poc-nap-rfx-adios-zir-lto"),
    ):
        if old not in text:
            raise RuntimeError(f"wrapper replacement missing: {old}")
        text = text.replace(old, new)
    if re.search("infi" + "nity", text, flags=re.IGNORECASE):
        raise RuntimeError("wrapper still contains the removed scheduler name")
    write(path, text)


def update_reflex() -> None:
    path = "scripts/apply-reflex-core.py"
    text = read(path)
    text = text.replace("apply_infinity_patch", "apply_bore_patch")
    text = text.replace(
        "-kn-marie-infinity-poc-nap-rfx-adios-zir-lto",
        "-kn-marie-bore-poc-nap-rfx-adios-zir-lto",
    )
    if re.search("infi" + "nity", text, flags=re.IGNORECASE):
        raise RuntimeError("REFLEX integrator still contains the removed scheduler name")
    write(path, text)


def update_dynamic_rewriter() -> None:
    path = "scripts/apply-dynamic-patch-sources.py"
    text = read(path)
    text = regex_once(
        text,
        r'    for prefix, name in \(\("INFINITY", "infinity"\), \("MARIE", "marie"\), \("REFLEX", "reflex"\)\):.*?\n\n    versions =',
        '''    for prefix, name in (("BORE", "bore"), ("MARIE", "marie"), ("REFLEX", "reflex")):
        record = component(lock, name)
        text = replace_assignment(text, f"{prefix}_REPO", repo_value(record))
        if f"{prefix}_COMMIT=" in text:
            text = replace_assignment(
                text, f"{prefix}_COMMIT", str(record.get("snapshot_commit", record["commit"]))
            )
        if f"{prefix}_PATCH_PATH=" in text:
            text = replace_assignment(text, f"{prefix}_PATCH_PATH", str(record["path"]))

    versions =''',
        "dynamic scheduler mapping",
    )
    text = replace_once(
        text,
        '        "infinity", "marie", "adios", "zram_ir", "poc", "nap", "reflex",',
        '        "bore", "marie", "adios", "zram_ir", "poc", "nap", "reflex",',
        "dynamic lock requirements",
    )
    if re.search("infi" + "nity", text, flags=re.IGNORECASE):
        raise RuntimeError("dynamic rewriter still contains the removed scheduler name")
    write(path, text)


def update_zarpon_integrator() -> None:
    path = "scripts/apply-zarpon-generic-name.py"
    text = read(path)
    text = text.replace(
        "-kn-marie-infinity-poc-nap-rfx-adios-zir-lto",
        "-kn-marie-bore-poc-nap-rfx-adios-zir-lto",
    )
    text = replace_once(
        text,
        '    resolver = root / "scripts/resolve-infinity-v46-cpu-series.py"\n',
        '    resolver = root / "scripts/resolve-patch-sources.py"\n',
        "generic patch resolver",
    )
    text = replace_once(
        text,
        '    infinity_rewriter = root / "scripts/patch-infinity-v46-build.py"\n',
        '    warning_rewriter = root / "scripts/apply-known-warning-fixes.py"\n'
        '    validation_rewriter = root / "scripts/apply-validation-modules.py"\n',
        "generic post-resolution helpers",
    )
    text = replace_once(
        text,
        '''    run_logged(
        [sys.executable, str(infinity_rewriter), str(core)],
        logs / "infinity-v46-build-rewrite.log",
    )
''',
        '''    run_logged(
        [sys.executable, str(warning_rewriter), str(core)],
        logs / "known-warning-fixes-rewrite.log",
    )
    run_logged(
        [sys.executable, str(validation_rewriter), str(core)],
        logs / "validation-modules-rewrite.log",
    )
''',
        "generic post-resolution execution",
    )
    if re.search("infi" + "nity", text, flags=re.IGNORECASE):
        raise RuntimeError("TurboDecky integrator still contains the removed scheduler name")
    write(path, text)


def update_config() -> None:
    path = "config/kernelnote.config"
    text = read(path)
    text = replace_once(
        text,
        "# Infinity v4.6-gpu integrates CPU/EEVDF, RT and DRM/GPU scheduling hooks.",
        "# BORE testing enhances upstream CFS/EEVDF using per-task burst behavior.",
        "static scheduler comment",
    )
    text = replace_once(
        text,
        "# CONFIG_SCHED_BORE is not set",
        "CONFIG_SCHED_BORE=y",
        "static BORE enablement",
    )
    write(path, text)


def update_workflow() -> None:
    path = ".github/workflows/validate-kernel.yml"
    text = read(path)
    text = replace_once(
        text,
        "  push:\n    branches: [integration/infinity-v46-full-gpu]\n",
        "",
        "obsolete integration-branch trigger",
    )
    text = text.replace("turbodecky-full-gpu-", "turbodecky-bore-testing-")
    verification = '''      - name: Verify BORE testing integration
        shell: bash
        run: |
          set -Eeuo pipefail
          grep -Fq 'Component: BORE scheduler testing' logs/01-bore-provenance.txt
          grep -Fq 'BORE testing patch applied successfully' logs/build.log
          test -s work/linux/kernel/sched/bore.c
          test -s work/linux/include/linux/sched/bore.h
          grep -Fq 'SCHED_BORE_VERSION' work/linux/include/linux/sched/bore.h
          grep -Fq 'sched_bore' work/linux/kernel/sched/bore.c
          grep -Fq 'CONFIG_SCHED_BORE=y' logs/final.config
          grep -Fq 'CONFIG_SCHED_POC_SELECTOR=y' logs/final.config
          python3 - <<'PY'
          import json
          from pathlib import Path
          lock = json.loads(Path('logs/patch-lock.json').read_text(encoding='utf-8'))
          bore = lock['components']['bore']
          assert bore['ref'] == 'main'
          assert bore['selection'] == 'exact'
          assert bore['kernel_target'] == '7.1'
          assert bore['selected_path'].startswith('patches/testing/')
          assert 'bore' in bore['selected_path'].lower()
          assert bore['project_version']
          assert len(bore['sha256']) == 64
          assert 'infinity' not in lock['components']
          PY

'''
    text = regex_once(
        text,
        r"      - name: Verify complete Infinity series and POC compatibility.*?(?=      - name: Verify validation module coverage)",
        verification,
        "workflow BORE verification",
    )
    text = regex_once(
        text,
        r"        if: >-\n          \(github\.event_name == 'push' &&.*?inputs\.publish_release\)",
        "        if: ${{ github.event_name == 'workflow_dispatch' && github.ref_name == 'main' && inputs.publish_release }}",
        "workflow release gate",
    )
    if re.search("infi" + "nity", text, flags=re.IGNORECASE):
        raise RuntimeError("workflow still contains the removed scheduler name")
    write(path, text)


def update_manual_test() -> None:
    path = "tests/test_manual_workflow_contract.py"
    text = read(path)
    text = replace_once(
        text,
        '        self.assertIn("github.ref_name == \'integration/infinity-v46-full-gpu\'", release_step)\n',
        '        self.assertNotIn("github.event_name == \'push\'", release_step)\n'
        '        self.assertNotIn("integration/", WORKFLOW)\n',
        "manual workflow release assertion",
    )
    write(path, text)


def update_readme() -> None:
    path = "README.md"
    text = read(path)
    text = replace_once(
        text,
        '''- **Responsividade e jogos:** Infinity CPU/EEVDF e POC Selector favorecem
  tarefas interativas, controlam o orçamento de CPU por EMA e escolhem CPUs
  ociosas considerando a topologia de cache, o que pode melhorar a latência
  percebida e a consistência do frame time.
- **Tarefas RT e espera:** Infinity também adiciona hooks de EMA para
  SCHED_FIFO/SCHED_RR e bypass seguro da proteção de fatia para tarefas que
  estão entrando em espera futex; isso não transforma o kernel em PREEMPT_RT.
''',
        '''- **Responsividade e jogos:** BORE modifica o CFS/EEVDF usando o tempo de
  rajada de cada tarefa para favorecer cargas interativas sob concorrência. O
  POC Selector continua escolhendo CPUs ociosas considerando LLC e topologia,
  o que pode melhorar a latência percebida e a consistência do frame time.
- **Carga em segundo plano:** a herança de rajada do BORE reduz a vantagem de
  processos que geram muitos filhos CPU-bound, preservando melhor a resposta do
  sistema durante compilação, descompressão e outras cargas paralelas.
''',
        "README scheduler benefits",
    )
    text = replace_once(
        text,
        "- **Infinity scheduler** — (https://github.com/galpt/infinity-scheduler): scheduler de CPU integrado ao CFS/EEVDF, modulação de vruntime e fatias por EMA, bypass futex e hooks de RT. ",
        "- **BORE testing** — [firelzrd/bore-scheduler](https://github.com/firelzrd/bore-scheduler/tree/main/patches/testing): aprimoramento do CFS/EEVDF orientado ao comportamento de rajada. O resolvedor exige um patch da série Linux 7.1, acompanha a árvore `testing` e registra commit e SHA-256 exatos em cada build.",
        "README scheduler source",
    )
    text = text.replace("`linux.<versão>.turbodecky.release`", "`<versão>.turbodecky`")
    if re.search("infi" + "nity", text, flags=re.IGNORECASE):
        raise RuntimeError("README still contains the removed scheduler name")
    write(path, text)


def update_patch_sources_doc() -> None:
    write(
        "PATCH-SOURCES.md",
        '''# Resolução dinâmica de patches

Antes de cada compilação, o TurboDecky resolve novamente as fontes descritas em
`config/patch-sources.json` usando a versão e a série estável do Linux obtidas
pelo workflow.

## Política

- a branch mantida pelo desenvolvedor é consultada no início de cada build;
- patches da mesma série do kernel têm prioridade;
- entre patches igualmente compatíveis, vence a versão mais nova do projeto;
- quando não existe patch para a série atual, pode ser escolhida a série anterior
  mais próxima apenas para componentes que permitem port controlado;
- componentes marcados como `require_exact_series` interrompem o build se não
  houver correspondência exata;
- commits históricos são usados apenas como fallback quando a branch atual
  removeu um arquivo ainda necessário;
- correções upstream de commit único permanecem imutáveis, pois não possuem uma
  linha de versões a acompanhar.

## BORE testing para Linux 7.1

O componente `bore` consulta o HEAD da branch `main` de
`firelzrd/bore-scheduler`, mas seleciona exclusivamente arquivos sob
`patches/testing/` cujo nome identifique a série Linux 7.1. O build falha se não
existir correspondência exata; patches de 6.18, 7.0 ou 7.2 não são portados
silenciosamente.

Entre candidatos 7.1 válidos, o resolvedor escolhe a versão BORE mais nova pelo
nome do arquivo. O patch precisa conter `SCHED_BORE_VERSION`,
`CONFIG_SCHED_BORE` e `kernel/sched/bore.c`. A configuração final força
`CONFIG_SCHED_BORE=y` e mantém PDS/BMQ desativados.

O registro contém o commit upstream, caminho selecionado, versão BORE extraída,
SHA-256 e tamanho. A aplicação tenta primeiro `patch --dry-run` sem fuzz; um port
controlado com fuzz máximo 3 só é aceito sem arquivos `.rej` e após verificações
semânticas dos arquivos e símbolos do BORE.

## Lock por build

O resolvedor cria `.resolved-patches/patch-lock.json` contendo, para cada
componente:

- repositório e branch consultados;
- commit upstream exato;
- commit do repositório Git mínimo e autocontido usado pelo build;
- caminho selecionado;
- série do kernel-alvo;
- versão do patch, quando disponível;
- SHA-256 e tamanho dos bytes aplicados;
- indicação de correspondência exata, fallback de série ou fallback de commit.

O build usa repositórios Git mínimos e autocontidos gerados a partir dos bytes
selecionados. Eles não dependem de lazy fetch. O lock é copiado para
`logs/patch-lock.json`.

## Componentes versionados

A resolução dinâmica cobre BORE testing, Marie LRU, ADIOS, ZRAM-IR, POC
Selector, NAP, REFLEX, patches TTM/DMEM de VRAM, linux-tkg, CachyOS, OpenWrt e a
configuração-base do Liquorix.

Patches de correção sem versão própria, como commits upstream específicos e
séries enviadas por e-mail, são baixados novamente e registrados por SHA-256,
mas continuam apontando para a revisão imutável escolhida.

## Validação local

```bash
scripts/validate-dynamic-patches-local.sh
```

Os testes confirmam:

- escolha da versão mais nova para a série exata;
- recusa de uma série BORE incompatível quando a série exata é obrigatória;
- uso exclusivo da árvore `patches/testing` para o BORE;
- escolha da série anterior compatível mais próxima somente nos componentes que
  permitem port;
- recuperação por commit histórico;
- consumo do snapshot como repositório Git local autocontido;
- preservação do lock e dos SHA-256;
- reescrita idempotente dos scripts de build;
- habilitação obrigatória de `CONFIG_SCHED_BORE=y`.
''',
    )


def update_validation_script() -> None:
    write(
        "scripts/validate-dynamic-patches-local.sh",
        '''#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m py_compile \\
  "$ROOT/scripts/resolve-latest-stable.py" \\
  "$ROOT/scripts/resolve-patch-sources.py" \\
  "$ROOT/scripts/apply-dynamic-patch-sources.py" \\
  "$ROOT/scripts/apply-validation-modules.py" \\
  "$ROOT/scripts/apply-known-warning-fixes.py" \\
  "$ROOT/scripts/patch-external-module-toolchain.py" \\
  "$ROOT/scripts/apply-zarpon-generic-name.py" \\
  "$ROOT/scripts/apply-latest-stable-series.py"
python3 -m json.tool "$ROOT/config/patch-sources.json" >/dev/null
python3 -m unittest -v \\
  "$ROOT/tests/test_latest_stable_identity.py" \\
  "$ROOT/tests/test_virtualbox_host_compat.py" \\
  "$ROOT/tests/test_external_module_toolchain.py" \\
  "$ROOT/tests/test_dynamic_patch_resolver.py" \\
  "$ROOT/tests/test_dynamic_patch_symlinks.py" \\
  "$ROOT/tests/test_dynamic_patch_indirections.py" \\
  "$ROOT/tests/test_bore_testing_source.py" \\
  "$ROOT/tests/test_validation_modules.py"
bash "$ROOT/tests/test_runtime_tuning.sh"

grep -Fq '"bore"' "$ROOT/config/patch-sources.json"
grep -Fq 'firelzrd/bore-scheduler.git' "$ROOT/config/patch-sources.json"
grep -Fq 'patches/testing/*linux{series}*bore*.patch' "$ROOT/config/patch-sources.json"
grep -Fq 'CONFIG_SCHED_BORE=y' "$ROOT/config/kernelnote.config"
grep -Fq 'resolve-patch-sources.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'apply-known-warning-fixes.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'apply-validation-modules.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'patch-external-module-toolchain.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
if grep -Fq 'patch-external-module-toolchain.py' "$ROOT/scripts/apply-latest-stable-series.py"; then
  echo "external module helper must not be owned by apply-latest-stable-series.py" >&2
  exit 1
fi
grep -Fq 'drivers/gpu/drm/amd/amdgpu/amdgpu.ko' "$ROOT/scripts/apply-validation-modules.py"
grep -Fq '"vram"' "$ROOT/config/patch-sources.json"
grep -Fq 'fallback_refs' "$ROOT/config/patch-sources.json"
grep -Fq 'patch-lock.json' "$ROOT/scripts/apply-dynamic-patch-sources.py"
grep -Fq 'KERNEL_VERSION' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'patch-source-resolution.log' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'turbodecky-snapshot' "$ROOT/scripts/resolve-patch-sources.py"
grep -Fq 'kvm.enable_virt_at_load=0' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_KVM_INTEL=m' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_KVM_AMD=m' "$ROOT/config/kernelnote.config"
grep -Fq 'TUNING_VERSION="1.3.2"' "$ROOT/scripts/build-tuning-package.sh"
grep -Fq 'Version: ${TUNING_VERSION}' "$ROOT/scripts/build-tuning-package.sh"
grep -Fq 'Depends: clang, llvm, lld, make' "$ROOT/scripts/build-tuning-package.sh"

legacy_scheduler_pattern='infi''nity'
if grep -Rni --exclude-dir=.git --exclude='*.pyc' -- "$legacy_scheduler_pattern" "$ROOT"; then
  echo "removed scheduler references remain in the repository" >&2
  exit 1
fi

echo "Dynamic BORE patch source validation passed"
''',
    )


def create_bore_test() -> None:
    write(
        "tests/test_bore_testing_source.py",
        '''#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/resolve-patch-sources.py"
SPEC = importlib.util.spec_from_file_location("resolve_patch_sources", MODULE_PATH)
assert SPEC and SPEC.loader
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


def patch(subject: str, version: str) -> str:
    return (
        f"From {'4' * 40} Mon Sep 17 00:00:00 2001\n"
        f"Subject: [PATCH] {subject}\n\n"
        "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c\n"
        "--- /dev/null\n+++ b/kernel/sched/bore.c\n@@ -0,0 +1,3 @@\n"
        f"+#define SCHED_BORE_VERSION \"{version}\"\n"
        "+#ifdef CONFIG_SCHED_BORE\n+int sched_bore;\n"
    )


class BoreTestingSourceTests(unittest.TestCase):
    def make_repo(self, root: Path, *, include_71: bool = True) -> Path:
        repo = root / "bore"
        repo.mkdir()
        run("git", "init", "-q", "-b", "main", cwd=repo)
        run("git", "config", "user.email", "test@example.invalid", cwd=repo)
        run("git", "config", "user.name", "Test", cwd=repo)
        testing = repo / "patches/testing"
        testing.mkdir(parents=True)
        if include_71:
            (testing / "0001-linux7.1-rc1-bore-6.8.0-rc1.patch").write_text(
                patch("linux7.1-rc1-bore-6.8.0-rc1", "6.8.0-rc1"), encoding="utf-8"
            )
        (testing / "0001-linux7.2-rc1-bore-6.9.0-rc1.patch").write_text(
            patch("linux7.2-rc1-bore-6.9.0-rc1", "6.9.0-rc1"), encoding="utf-8"
        )
        stable = repo / "patches/stable"
        stable.mkdir()
        (stable / "0001-linux7.1-bore-9.9.9.patch").write_text(
            patch("linux7.1-bore-9.9.9", "9.9.9"), encoding="utf-8"
        )
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "fixture", cwd=repo)
        return repo

    @staticmethod
    def manifest(repo: Path) -> dict[str, object]:
        return {
            "schema": 1,
            "components": {
                "bore": {
                    "kind": "git_patch",
                    "repo": str(repo),
                    "ref": "main",
                    "exact_globs": ["patches/testing/*linux{series}*bore*.patch"],
                    "fallback_globs": [],
                    "require_exact_series": True,
                    "output": "01-bore.patch",
                    "project_version_regex": r"bore[-_]?v?([0-9]+(?:\.[0-9]+)+(?:-rc[0-9]+|r[0-9]+)?)",
                    "required_markers": ["SCHED_BORE_VERSION", "CONFIG_SCHED_BORE", "kernel/sched/bore.c"],
                }
            },
        }

    def test_selects_exact_71_testing_patch_and_ignores_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            output = root / "resolved"
            lock = resolver.resolve(
                self.manifest(repo), output, resolver.KernelVersion.parse("7.1.4"), "7.1"
            )
            record = lock["components"]["bore"]
            self.assertEqual(record["selection"], "exact")
            self.assertEqual(record["kernel_target"], "7.1")
            self.assertEqual(record["project_version"], "6.8.0-rc1")
            self.assertIn("/testing/", f"/{record['selected_path']}")
            self.assertNotIn("9.9.9", record["selected_path"])
            self.assertEqual(len(record["sha256"]), 64)

    def test_missing_71_testing_patch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root, include_71=False)
            with self.assertRaises(resolver.ResolverError):
                resolver.resolve(
                    self.manifest(repo), root / "resolved",
                    resolver.KernelVersion.parse("7.1.4"), "7.1",
                )

    def test_repository_configuration_enables_bore(self) -> None:
        manifest = json.loads((ROOT / "config/patch-sources.json").read_text(encoding="utf-8"))
        self.assertIn("bore", manifest["components"])
        self.assertNotIn("infi" + "nity", manifest["components"])
        config = (ROOT / "config/kernelnote.config").read_text(encoding="utf-8")
        self.assertIn("CONFIG_SCHED_BORE=y", config)


if __name__ == "__main__":
    unittest.main()
''',
    )


def delete_legacy_files() -> None:
    for relative in (
        "INFINITY-POC-COMPATIBILITY.md",
        "config/infinity-source.json",
        "scripts/resolve-infinity-v46-cpu-series.py",
        "scripts/resolve-infinity-v46-cpu-series-lib.py",
        "scripts/patch-infinity-v46-build.py",
        "scripts/validate-infinity-poc-compat.py",
        "tests/test_infinity_v46_cpu_series.py",
    ):
        (ROOT / relative).unlink(missing_ok=True)


def remove_bootstrap_files() -> None:
    (ROOT / "scripts/migrate-to-bore.py").unlink(missing_ok=True)
    (ROOT / ".github/workflows/migrate-to-bore.yml").unlink(missing_ok=True)


def validate_repository() -> None:
    legacy = "infi" + "nity"
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix == ".pyc":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if legacy.lower() in text.lower():
            offenders.append(str(path.relative_to(ROOT)))
    if offenders:
        raise RuntimeError("legacy scheduler references remain: " + ", ".join(sorted(offenders)))

    manifest = json.loads(read("config/patch-sources.json"))
    bore = manifest["components"]["bore"]
    assert bore["repo"] == "https://github.com/firelzrd/bore-scheduler.git"
    assert bore["require_exact_series"] is True
    assert bore["exact_globs"] == ["patches/testing/*linux{series}*bore*.patch"]
    assert "CONFIG_SCHED_BORE=y" in read("config/kernelnote.config")


def main() -> None:
    update_manifest()
    update_core()
    update_wrapper()
    update_reflex()
    update_dynamic_rewriter()
    update_zarpon_integrator()
    update_config()
    update_workflow()
    update_manual_test()
    update_readme()
    update_patch_sources_doc()
    update_validation_script()
    create_bore_test()
    delete_legacy_files()
    remove_bootstrap_files()
    validate_repository()
    print("BORE migration completed and repository invariants passed")


if __name__ == "__main__":
    main()
