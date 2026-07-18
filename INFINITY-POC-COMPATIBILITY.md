# Infinity v4.6-gpu e POC Selector

## Resultado da análise

O POC foi mantido nesta branch de teste.

Os patches Infinity `0001`–`0003` e o POC compartilham alterações nos arquivos centrais do scheduler de CPU. Essa combinação já foi compilada integralmente no workflow 161.

Os patches Infinity `0004`–`0006` alteram somente o scheduler DRM e cabeçalhos DRM. O POC não altera esses caminhos, portanto não existe nova sobreposição direta.

O POC também preserva o bypass em topologias de capacidade assimétrica. Nesses sistemas, a preferência do Infinity por CPUs de maior capacidade continua ativa.

O acoplamento GPU usa o estado EMA e futex mantido pelo Infinity na tarefa proprietária. O POC não modifica esse estado.

## Validação

O script `scripts/validate-infinity-poc-compat.py` verifica automaticamente:

- que a parte GPU permanece restrita ao DRM;
- que a parte GPU e o POC não modificam os mesmos arquivos;
- que o POC mantém o gate para topologias assimétricas;
- que o acoplamento GPU continua usando o estado do Infinity;
- que a parte GPU não passa a controlar estado interno do POC.

A branch deve ser submetida a testes comparativos com o POC ativado e desativado antes de qualquer integração definitiva.
