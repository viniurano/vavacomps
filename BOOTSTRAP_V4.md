# Bootstrap inicial v4

A carga inicial usa os JSONs versionados no repositorio e **nao faz requisicoes ao VLR**.

## Antes de executar

1. Se voce coletou dados novos na sua maquina, envie os arquivos JSON atualizados para a branch `feature/backend-dinamico-v3`, dentro de `dados/`. Confira os diffs antes do commit; nao substitua arquivos por versoes mais antigas.
2. Confira se os arquivos de campeonatos possuem `event_id`, `equipes`, `team_id` e `mapas` com `game_id`. Arquivos sem `event_id` sao ignorados, para nao misturar torneios.
3. Acesse **Actions > Vava Comps v4 - coleta agendada > Run workflow**.
4. Escolha a branch `feature/backend-dinamico-v3` e a tarefa **bootstrap**.
5. Apos concluir, verifique o log e os novos JSONs em `dados/v4/eventos/`. O workflow faz commit dos dados na mesma branch.

A tarefa bootstrap pode ser repetida: nao duplica `game_id` e nao sobrescreve mapas ja presentes no v4. Nao faz descoberta de partidas faltantes nem consultas externas.

## Importante antes de publicar

- O cron do GitHub Actions so fica ativo na branch padrao. Publicar o site estatico, por si so, **nao ativa a automacao**.
- O botao de atualizar time no site atualmente grava no disco do backend, mas nao faz commit no GitHub. Em hospedagem temporaria os dados podem se perder.
- A agenda VLR e os testes de coleta +2h/+3h ainda precisam de validacao. Nao considere a sincronizacao semanal garantida ate confirmar a infraestrutura.
- Este workflow nao publica o site nem faz merge para `main`.
