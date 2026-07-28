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
- consultas Git remotas não são interativas e têm limite de tempo; uma origem
  lenta ou indisponível falha de forma explícita em vez de bloquear o build.

## BORE atual e coexistência com sched_ext

O resolvedor consulta os patches oficiais de BORE para a série estável atual
nas árvores `testing` e `stable` de
[`firelzrd/bore-scheduler`](https://github.com/firelzrd/bore-scheduler/tree/main/patches/testing)
e escolhe a versão mais nova com correspondência de série exata. Os bytes do
patch selecionado, commit, caminho, tamanho e SHA-256 entram no
`patch-lock.json`; o finalizador aplica exatamente esse arquivo materializado.
Não há hash aprovado fixo no manifesto para impedir uma atualização legítima.

O patch upstream BORE é aplicado somente depois de `patch --dry-run` contra a
árvore Linux baixada para aquele build. Assim, um patch novo que não tenha
contexto compatível falha antes de modificar a árvore ou publicar um pacote;
nenhuma aplicação usa `--fuzz`.

O lock também resolve
[`0002-sched-ext-coexistence-fix.patch`](https://github.com/firelzrd/bore-scheduler/tree/main/patches/additions).
Como esse helper precisa de contexto e de um protótipo específicos da série
Linux 7.1, o finalizador gera um port derivado a cada build. Ele mantém apenas
o contexto revisado de `fair.c` e a declaração em `include/linux/sched/bore.h`,
copiando o corpo atual de `reweight_task()` dos bytes upstream bloqueados. O
registro `compatibility_port` no lock contém SHA-256, tamanho, alvo do kernel,
adaptador e SHA-256 da fonte pai.

Essa adaptação falha fechada se o patch upstream deixar de ter exatamente uma
função `reweight_task()` em `kernel/sched/fair.c`, perder os marcadores
necessários ou se o template revisado mudar de estrutura. O port materializado
é validado pelo lock antes do download da árvore Linux e novamente por
`patch --dry-run` antes da aplicação. A compilação cobre `bore.o`, `fair.o`,
`core.o` e `build_utility.o` com `CONFIG_SCHED_BORE=y`.

## BORE e POC Selector

O POC Selector continua sendo aplicado após BORE. A validação local confirma
que ambos aplicam sem rejeitos sobre Linux 7.1.4 e que `fair.o` compila com
`CONFIG_SCHED_BORE=y` e `CONFIG_SCHED_POC_SELECTOR=y`. O arquivo
`kernel/sched/poc_selector.c` é incluído por `fair.c`; não é uma unidade de
compilação independente.

## Perfil Zen interativo sem alterações em THP

`CONFIG_ZEN_INTERACTIVE=y` é obtido da branch oficial
[`zen-kernel/zen-kernel:<série>/zen-sauce`](https://github.com/zen-kernel/zen-kernel/branches),
selecionando a série estável exata ou a série oficial anterior mais próxima. O
resolvedor segue o HEAD atual dessa branch, localiza o commit que introduziu o
perfil e gera um patch mínimo apenas com hunks condicionados por
`CONFIG_ZEN_INTERACTIVE`. Ele também busca na história da mesma branch os
commits compatíveis de `evdev` (`call_rcu`) e do Kconfig dos drivers P-State,
que não pertencem ao hunk condicionado do perfil. Esses commits são
materializados novamente a cada build e registrados no `patch-lock.json` com
commit, caminho e SHA-256; não são patches estáticos adicionados ao repositório.

A política de THP permanece independente do perfil Zen:

- qualquer hunk que altere `mm/huge_memory.c`, `TRANSPARENT_HUGEPAGE`,
  `khugepaged` ou símbolos `THP_*` é removido do patch gerado;
- o SHA-256 de `mm/huge_memory.c` é calculado antes e depois da aplicação e o
  build falha se houver qualquer diferença;
- o lock registra `thp_policy: preserved-unchanged` e a quantidade de hunks THP
  excluídos;
- o lock registra a série selecionada e as fontes dos commits de compatibilidade
  Zen que completam o perfil;
- a configuração e os parâmetros THP já definidos pelo projeto não são
  substituídos, redefinidos nem condicionados por `CONFIG_ZEN_INTERACTIVE`.

## Fallback local do Marie LRU

A versão mais recente e compatível do Marie LRU também é mantida em
`patches/fallback/lru_marie.patch`, acompanhada por metadados com commit,
caminho, versão, tamanho e SHA-256. O resolvedor usa esses bytes somente quando
a consulta ao repositório oficial falha; a seleção fica registrada como
`local-fallback` no `patch-lock.json`.

O workflow `update-marie-fallback.yml` consulta o upstream a cada hora, após
alterações relevantes na `main` ou por disparo manual. Quando encontra uma
versão nova, atualiza o patch local, seus metadados e os defaults do script-base.
Se a branch principal não aceitar escrita direta, ele abre uma pull request de
atualização automaticamente.

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

Quando uma fonte precisa de um contexto de compatibilidade mantido pelo
projeto, o mesmo componente pode incluir `compatibility_port`: o arquivo
derivado, sua identidade de adaptador, versão-alvo, SHA-256, tamanho e o
SHA-256 do upstream de origem. A validação rejeita qualquer port que não seja
filho exato da fonte bloqueada.

O build usa repositórios Git mínimos e autocontidos gerados a partir dos bytes
selecionados. Eles não dependem de lazy fetch. O lock é copiado para
`logs/patch-lock.json`.

## Componentes versionados

A resolução dinâmica cobre BORE, sua correção de coexistência com `sched_ext`,
Marie LRU, ADIOS, ZRAM-IR, POC Selector, NAP, REFLEX, o perfil Zen interativo,
patches TTM/DMEM de VRAM, linux-tkg, CachyOS, OpenWrt e a configuração-base do
Liquorix.

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
- rastreamento do patch BORE upstream, da correção de coexistência com
  `sched_ext` e de seu port derivado bloqueado;
- aplicação combinada de BORE e POC Selector;
- aplicação do perfil Zen com exclusão e invariância verificável de THP;
- reescrita das validações de build.
