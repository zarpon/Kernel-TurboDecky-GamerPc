#!/usr/bin/env python3
"""Build auditable TurboDecky notes, with a bounded GitHub upstream commit sample."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

PATCH_NAMES = {
    'bore': 'BORE', 'bore_sched_ext_coexistence': 'BORE sched_ext coexistence',
    'lru_cast': 'LRU CAST', 'nap': 'NAP', 'poc_selector': 'POC Selector',
    'reflex': 'REFLEX', 'adios': 'ADIOS', 'zram_ir': 'ZRAM-IR',
}
TOPICS = (
    ('Gráficos e GPU', r'\b(?:drm|amdgpu|radeon|nouveau|i915|xe|gpu)\b'),
    ('Processador e escalonamento', r'\b(?:sched|scheduler|cpufreq|amd-pstate|intel_pstate|x86)\b'),
    ('Armazenamento e sistemas de arquivos', r'\b(?:ext4|btrfs|xfs|nvme|block|io_uring|filesystem)\b'),
    ('Rede', r'\b(?:net|tcp|wifi|wireless|ethernet|bluetooth)\b'),
    ('Drivers e dispositivos', r'\b(?:usb|hid|input|sound|alsa|pci|thunderbolt)\b'),
    ('Memória', r'\b(?:mm|memory|zram|swap|folio|reclaim)\b'),
)


def clean(value: object) -> str:
    return str(value).replace('\r', ' ').replace('\n', ' ').replace('|', '\\|').replace('`', "'").strip()


def previous_linux(version: str) -> tuple[str, str, str] | None:
    rc = re.fullmatch(r'(\d+)\.(\d+)-rc(\d+)', version)
    if rc:
        major, minor, number = map(int, rc.groups())
        previous = f'v{major}.{minor}-rc{number-1}' if number > 1 else f'v{major}.{minor-1}'
        return 'torvalds/linux', previous, 'v' + version
    stable = re.fullmatch(r'(\d+)\.(\d+)(?:\.(\d+))?', version)
    if not stable:
        return None
    major, minor = map(int, stable.groups()[:2])
    fix = stable.group(3)
    if fix is not None:
        previous = f'v{major}.{minor}.{int(fix)-1}' if int(fix) > 1 else f'v{major}.{minor}'
        return 'gregkh/linux', previous, 'v' + version
    return 'torvalds/linux', f'v{major}.{minor-1}', 'v' + version


def linux_changes(version: str) -> list[str]:
    refs = previous_linux(version)
    if refs is None:
        raise ValueError('invalid kernel version')
    repo, base, head = refs
    compare = f'https://github.com/{repo}/compare/{base}...{head}'
    lines = [f'- **Comparação upstream:** [{base} → {head}]({compare}).']
    try:
        result = subprocess.run(
            ['gh', 'api', '-X', 'GET', f'repos/{repo}/compare/{base}...{head}', '-f', 'per_page=100'],
            text=True, capture_output=True, check=False, timeout=40,
        )
        if result.returncode != 0:
            raise RuntimeError(f'GitHub API exit status {result.returncode}')
        data = json.loads(result.stdout)
        commits = data['commits']
        if not isinstance(commits, list):
            raise ValueError('GitHub API commits list is invalid')
        total = data.get('total_commits')
        lines.append(f'- **Amostra:** {len(commits)} commits de {total if isinstance(total, int) else "total não informado"}; seleção temática, **não é um changelog completo**.')
        chosen = set()
        for label, expression in TOPICS:
            found = None
            for item in commits:
                subject = str(item.get('commit', {}).get('message', '')).splitlines()[0]
                sha = str(item.get('sha', ''))
                if not sha or sha in chosen or not re.search(expression, subject, re.I):
                    continue
                if subject.lower().startswith(('merge ', 'linux ', 'revert ')):
                    continue
                found = (sha, subject)
                break
            if found:
                sha, subject = found
                chosen.add(sha)
                lines.append(f'- **{label}:** {clean(subject)} ([commit]({"https://github.com/" + repo + "/commit/" + sha})).')
        if not chosen:
            lines.append('- A amostra não trouxe mudanças específicas das categorias acompanhadas; consulte a comparação upstream.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        lines.append(f'- Resumo automático indisponível nesta execução ({clean(type(exc).__name__)}); a comparação upstream acima é a referência oficial. Nenhuma novidade foi inferida sem evidência.')
    return lines


def patch_table(lock: dict) -> list[str]:
    components = lock.get('components')
    if not isinstance(components, dict) or not components:
        raise ValueError('patch lock is missing components')
    lines = ['| Componente | Versão | Kernel do patch | Seleção |', '|---|---|---|---|']
    details = []
    for key, data in sorted(components.items()):
        if not isinstance(data, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(data.get('sha256', ''))):
            raise ValueError(f'patch lock is incomplete: {key}')
        name = PATCH_NAMES.get(key, key.replace('_', ' '))
        version = data.get('project_version') or 'não declarada (ver fonte)'
        target = data.get('kernel_target') or 'genérico / não declarado'
        method = data.get('selection') or 'não declarada'
        lines.append(f'| **{clean(name)}** | `{clean(version)}` | `{clean(target)}` | {clean(method)} |')
        details += [f'**{clean(name)}**', f'- Origem: `{clean(data.get("repo") or data.get("url") or "local")}`',
                    f'- Arquivo: `{clean(data.get("selected_path") or data.get("path") or data.get("output") or "unknown")}`',
                    f'- Commit fixado: `{clean(data.get("commit") or "não se aplica")}`',
                    f'- SHA256 exato: `{data["sha256"]}`']
        port = data.get('compatibility_port')
        if isinstance(port, dict):
            if not re.fullmatch(r'[0-9a-f]{64}', str(port.get('sha256', ''))):
                raise ValueError(f'incomplete port checksum: {key}')
            details += [f'- Adaptação revisada: `{clean(port.get("adapter") or port.get("output") or "port")}`',
                        f'- SHA256 do porte: `{port["sha256"]}`']
        if data.get('latest_upstream_project_version'):
            details.append(f'- Revisão global upstream: `{clean(data["latest_upstream_project_version"])}`')
        details.append('')
    return lines + ['', '<details>', '<summary>Fontes, commits e checksums completos dos patches</summary>', ''] + details + ['</details>']


def render(lock: dict, version: str, kernel_release: str, tag: str, zip_name: str, sha: str, run_id: str, include_upstream: bool = True) -> str:
    if lock.get('kernel', {}).get('version') != version:
        raise ValueError('kernel version does not match patch lock')
    if not tag.startswith(kernel_release + '-'):
        raise ValueError('release tag differs from the built kernel identity')
    lines = [f'# TurboDecky GamerPc — Linux {clean(version)}', '', '## Kernel compilado',
             f'- **Linux upstream:** `{clean(version)}` ({"RC/pré-lançamento" if "-rc" in version else "stable"}).',
             f'- **Kernel instalado:** `{clean(kernel_release)}`; **tag:** `{clean(tag)}`.',
             f'- **Branch:** `main`; **commit:** `{clean(sha)}`; **run:** `{clean(run_id)}`.',
             '- **Perfil:** x86_64 genérico (sem `-march=native`); Clang/LLVM, **Full LTO**, BORE e POC Selector verificados no build.',
             '', '## Principais mudanças do Linux upstream',
             'Resumo de **commits reais upstream** entre tags; não confundir com as alterações TurboDecky.']
    if include_upstream:
        lines += linux_changes(version)
    lines += ['', '## Patches selecionados nesta compilação',
              'Versões extraídas do lock produzido e validado pelo build. Sem inferir versão ausente no metadata.',
              '', *patch_table(lock), '', '## Pacotes e verificação',
              f'- Bundle ZIP: `{clean(zip_name)}`; pacotes Debian `.deb` e `SHA256SUMS`.',
              '- Logs de build, configuração final e `patch-lock.json` documentam os recursos e fontes utilizados.',
              '- Um novo build do mesmo Linux pode atualizar os patches ou pacotes sem alterar a versão base do kernel.']
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser()
    for arg in ('lock', 'kernel-version', 'kernel-release', 'tag', 'zip', 'output'):
        parser.add_argument('--' + arg, required=True)
    a = parser.parse_args()
    lock = json.loads(Path(a.lock).read_text(encoding='utf-8'))
    notes = render(lock, a.kernel_version, a.kernel_release, a.tag, a.zip,
                   os.getenv('GITHUB_SHA', 'local'), os.getenv('GITHUB_RUN_ID', 'local'))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(notes, encoding='utf-8')
    print(f'Generated {out}: {len(lock["components"])} components')


if __name__ == '__main__':
    main()
