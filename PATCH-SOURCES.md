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

## Lock por build

O resolvedor cria `.resolved-patches/patch-lock.json` contendo, para cada
componente:

- repositório e branch consultados;
- commit exato;
- caminho selecionado;
- série do kernel-alvo identificada no nome;
- versão do patch, quando disponível;
- SHA-256 e tamanho dos bytes aplicados;
- indicação de correspondência exata, fallback de série ou fallback de commit.

O build usa os snapshots locais desse lock, não volta a consultar a rede durante
a aplicação e copia o lock para `logs/patch-lock.json`.

## Componentes versionados

A resolução dinâmica cobre Infinity v3, Marie LRU, ADIOS, ZRAM-IR, POC
Selector, NAP, REFLEX, patches TTM/DMEM de VRAM, linux-tkg, CachyOS, OpenWrt e a
configuração-base do Liquorix.

Patches de correção sem versão própria, como commits upstream específicos e
séries enviadas por e-mail, são baixados novamente e registrados por SHA-256,
mas continuam apontando para a revisão imutável escolhida.

## Validação local

```bash
scripts/validate-dynamic-patches-local.sh
```

Os testes usam repositórios Git locais e confirmam:

- escolha da versão mais nova para a série exata;
- escolha da série anterior compatível mais próxima;
- falha quando uma série exata obrigatória não existe;
- recuperação por commit histórico;
- consumo do snapshot como repositório Git local;
- reescrita idempotente dos scripts de build.
