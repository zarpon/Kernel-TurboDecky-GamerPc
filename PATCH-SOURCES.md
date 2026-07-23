# Resolução dinâmica de patches

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
