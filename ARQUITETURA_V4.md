# Vava Comps v4 — armazenamento e coleta (2026)

## Camadas

1. `dados/v4/catalogo_2026.json`: fonte de verdade para IDs, nomes e regiões dos **16 eventos** (12 regionais, 2 Masters, Champions, GC Championship). O cadastro não significa que partidas foram coletadas. Pools não verificadas permanecem `null`.
2. `dados/v4/eventos/<event_id>.json`: um arquivo por evento. Preserva `equipes`, `series`, `meta`, mapas e estatísticas existentes. Arquivo vazio com `meta.status=aguardando_dados` é apenas placeholder.
3. `dados/v4/agenda.json`: fila de partidas agendadas; não deve ser confundida com dados já coletados.
4. `backend/v4_audit.py`: auditoria offline de cobertura, IDs e duplicações.
5. `backend/v4_store.py`: importação local e atualização de partidas. **Somente `schedule` e `run` podem consultar VLR.**

## Execução segura

- `python -m backend.v4_store bootstrap`: importa apenas os snapshots locais existentes, deduplica por `game_id` dentro de cada equipe, cria placeholders dos eventos faltantes e imprime auditoria. **Zero consultas VLR**. Não substitui mapas já existentes.
- `python -m backend.v4_store audit`: imprime auditoria, sem gravar arquivos nem consultar rede.
- `python -m backend.v4_store schedule`: consulta o calendário VLR (operação de rede, não executar como parte do bootstrap).
- `python -m backend.v4_store run`: consulta partidas vencidas (operação de rede, não executar como parte do bootstrap).

## Limitações atuais — não considerar pronto para produção

- Bootstrap **não preenche eventos regionais/Masters** se não houver snapshots locais para eles. A auditoria mostrará `aguardando_dados`.
- `dados/vct_comps_geral.json` pode estar vazio ou em formato incompatível e será ignorado.
- `dados/v4/eventos` registra partidas por campeonato, mas não comprova cobertura completa; `dados_parciais` é intencional.
- Coleta incremental, controle de requisições entre processos, identificação confiável de eventos no calendário e leitura 100% offline pela interface precisam de validação antes de habilitar coleta automática ou publicar.
- Nunca fazer backfill histórico em massa no VLR sem orçamento explícito de requisições, pausas, persistência de progresso e parada ao primeiro 429.
- GitHub Actions agendado só roda na branch padrão. O workflow manual em `main` executa o bootstrap na branch `feature/backend-dinamico-v3` e faz push somente nela.

## Próximas etapas

1. Executar bootstrap manual novamente para cadastrar os 16 eventos e gerar auditoria.
2. Conferir a cobertura por evento e map pools por patch; marcar `map_pool_confirmed` somente após validação.
3. Implementar descoberta histórica com fila persistente, orçamento de chamadas e retomada incremental, separada da leitura do site.
4. Validar que GETs do frontend/backend leem somente JSON antes de publicar.
