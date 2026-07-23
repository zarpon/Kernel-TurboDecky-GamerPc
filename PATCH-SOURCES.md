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

## BORE 6.6.3 para Liquorix 7.1.3

O resolvedor exige o patch estável upstream de BORE para Linux 7.1 em
[`firelzrd/bore-scheduler`](https://github.com/firelzrd/bore-scheduler/tree/main/patches/stable/linux-6.18-bore).
O lock registra seu commit, caminho e SHA-256. O fonte do TurboDecky, porém,
é a tag Liquorix `v7.1.3-lqx1`, que muda os mesmos blocos EEVDF e debugfs; por
isso o patch upstream puro não é aplicado diretamente.

O build usa `patches/bore/7.1.3-lqx1-bore-6.6.3.patch`, uma adaptação mínima
revisada contra essa tag. Antes de aplicá-la sem fuzz, ele baixa e verifica o
patch upstream correspondente. A compilação local cobre `bore.o`, `fair.o`,
`core.o` e `build_utility.o` com `CONFIG_SCHED_BORE=y`.

## BORE e POC Selector

O POC Selector continua sendo aplicado após BORE. A validação local confirma
que ambos aplicam sem rejeitos sobre Liquorix 7.1.3 e que `fair.o` compila com
`CONFIG_SCHED_BORE=y` e `CONFIG_SCHED_POC_SELECTOR=y`. O arquivo
`kernel/sched/poc_selector.c` é incluído por `fair.c`; não é uma unidade de
compilação independente.

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

A resolução dinâmica cobre BORE, Marie LRU, ADIOS, ZRAM-IR, POC Selector, NAP,
REFLEX, patches TTM/DMEM de VRAM, linux-tkg, CachyOS, OpenWrt e a
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
- escolha da série anterior compatível mais próxima;
- falha quando uma série exata obrigatória não existe;
- recuperação por commit histórico;
- consumo do snapshot como repositório Git local autocontido;
- rastreamento do patch BORE upstream e do port Liquorix versionado;
- aplicação combinada de BORE e POC Selector;
- reescrita das validações de build.
