# Auditoria de patches: Charcoal → TurboDecky GamerPc

Auditoria realizada em 2026-07-25 comparando o `PKGBUILD` e
`automation/patch-sources.json` de `linux-charcoal-vulcano` com o manifesto e
os scripts de geração do `Kernel-TurboDecky-GamerPc`.

## Patches do Charcoal e destino no GamerPC

| Fonte/patch observado no Charcoal | Destino no GamerPC | Resultado |
| --- | --- | --- |
| BORE 6.8.0-rc1 | `bore` + `patches/bore/7.1.4-bore-6.8.0-rc1.patch` | Equivalente compatível; fonte oficial é resolvida por série e o port revisado é validado por SHA-256 |
| BORE `sched-ext` coexistence fix | `bore_sched_ext_coexistence` + `patches/bore/7.1.4-sched-ext-coexistence-fix.patch` | Coberto |
| Marie LRU 0.6.7 | `marie` | Coberto por resolução dinâmica; o fallback local é sincronizado automaticamente com a versão upstream compatível mais recente |
| ZRAM-IR 1.2 | `zram_ir` | Coberto por fonte compatível de Linux 7.1 |
| POC Selector 2.6.1r2 | `poc` | Coberto por versão mais nova compatível, atualmente 2.6.2r2 |
| NAP 0.5.0 | `nap` | Coberto por port controlado da fonte estável compatível |
| ADIOS 3.2.0 e patch de default | `adios` | Coberto; default ADIOS continua explícito |
| C23 libbpf | `c23_libbpf` | Coberto |
| Linux-tkg `clear-patches` | `clear` | Coberto |
| Linux-tkg `fsync1_via_futex_waitv` | `fsync` | Coberto |
| Linux-tkg `optimize_harder_O3` | `o3` | Coberto |
| Gentoo Bluetooth SSP key sizes | `bt_ssp` | Coberto |
| Gentoo libbpf uninitialized workaround | `libbpf_uninitialized` | Coberto |
| Gentoo CPU optimizations | `cpu_optimizations` | Coberto |
| CachyOS DKMS clang | `dkms_clang` | Coberto |
| CachyOS Clang Polly | `clang_polly` | Coberto |
| Gentoo firmware file name | `firmware_name` | Coberto |
| OpenWrt minstrel 302 | `minstrel_frac` | Coberto |
| OpenWrt minstrel 303 | `minstrel_fluctuation` | Coberto |
| OpenWrt minstrel 304 | `minstrel_downgrade` | Coberto por port para a série atual |
| OpenWrt ath11k 910 remapped CE | `ath11k_remapped_ce` | Coberto |
| CodeLinaro ath11k `DISABLE_KEY` revert | `ath11k_disable_key` | Coberto |
| Qualcomm ath11k upstream series | `ath11k_upstream` | Coberto |
| REFLEX CPUFreq 0.3.1 | `reflex` | Coberto; `intel_pstate` e `amd_pstate` ficam em `passive` |
| Zen: evdev `call_rcu`, remoção da dependência schedutil dos P-State e cinco hunks do perfil interativo | `zen_interactive` | Coberto pelo perfil oficial da série selecionada |
| Zen: os dois commits equivalentes modernos de evdev e P-State | `zen_interactive.compatibility_sources` | Integrados neste PR; são buscados a cada build na branch oficial mais nova compatível |

## Itens específicos do Steam Deck que não devem ser copiados

Os arquivos `vangogh_allow_higher_cpu_freq.patch`,
`vangogh_higher_max_power_limit.patch`, `ryzen_smu.diff` e
`xpad-noone.diff` são específicos do hardware/árvore Steam Deck do Charcoal.
Aplicá-los no kernel genérico do GamerPC introduziria alterações de plataforma
sem alvo compatível. Os repositórios DKMS `ryzen_smu`, `xone`, `xpad-noone` e
`xpadneo` também não são patches da árvore Linux; continuam fora do patchset
genérico do GamerPC.

## Política de atualização

Nenhum patch novo deste PR é um arquivo estático versionado. O resolver Zen
consulta `refs/heads/*/zen-sauce`, escolhe a série exata ou a série anterior
compatível mais próxima, seleciona o HEAD atual e localiza os dois commits de
compatibilidade na história daquela branch. O patch materializado, os commits,
os caminhos, a série, o SHA-256 e o tamanho ficam no `patch-lock.json` de cada
build. Se a fonte deixar de aplicar, o fluxo tenta o port controlado com fuzz
limitado e grava os rejeitos; qualquer rejeito não resolvido interrompe o build.

O GamerPC também contém componentes que não existiam no Charcoal, como VRAM/
TTM e a configuração Liquorix genérica.
