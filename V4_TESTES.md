# Vava Comps v4 — coleta incremental (branch de desenvolvimento)

## Fluxo planejado
- 00:00 America/Sao_Paulo: ler uma vez a pagina de calendario do VLR e persistir `dados/v4/agenda.json`.
- Cada serie com timestamp e evento identificados recebe consultas em +2h e +3h do inicio previsto.
- Cada coleta salva os mapas das **duas** equipes em `dados/v4/eventos/<event_id>.json`, por `game_id`, sem apagar mapas antigos.
- Na tela Time, o botao Atualizar dados consulta **somente as series da equipe no campeonato selecionado** e atualiza os JSONs locais.
- As leituras do time e do placar usam o JSON v4 quando disponivel. Dados ainda nao migrados continuam usando o backend v3.
- O cooldown de 15 minutos evita repeticao por serie/equipe dentro do mesmo processo.

## Executar localmente
```bash
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 8001
python -m http.server 8000
```
Em outro terminal, para verificar a coleta (somente quando o acesso ao VLR estiver disponivel):
```bash
python -m backend.v4_store schedule
python -m backend.v4_store run
```
O arquivo `.github/workflows/v4-sync.yml` tem execucao manual e agendamentos de 00h (03:00 UTC) e verificacao de fila a cada 15 min. **GitHub Actions so executa cron automaticamente na branch padrao**, portanto a automacao nao entra em operacao enquanto esta branch nao for publicada/autorizada. Os cron jobs podem sofrer atraso.

## Validacoes pendentes
1. Confirmar no HTML atual de `https://www.vlr.gg/matches/` os seletores dos cards, timestamps e ID do evento. Se o VLR nao expuser o ID do evento no card, sera necessario resolver o vinculo pelo indice de eventos. Sem isso, o job registra `evento_nao_identificado` e nao baixa a serie.
2. Testar MD3 e MD5 com jogos reais e conferir se os mapas aparecem corretamente em +2h/+3h.
3. Validar `vlrdevapi==3.1.0` com series que estejam em andamento e estatisticas parciais.
4. Implementar persistencia compartilhada para o botao no ambiente hospedado: no momento o endpoint grava no disco do backend, nao faz commit no GitHub. Se o servidor tiver armazenamento efemero, essa atualizacao nao sobrevivera ao reinicio.
5. Adicionar controle persistente de rate limit/429 e controle de concorrencia entre instancias (o lock atual protege um unico processo).
6. Verificar como o calendario lida com jogos adicionados apos 00h, horarios alterados e series que cruzam a meia-noite; a arquitetura deliberadamente nao revisa a agenda durante o dia.
7. Migrar os JSONs historicos para o esquema v4 e remover as rotas de consulta direta ao VLR na navegacao. Por enquanto o modo v3 continua como fallback.
8. Antes de expor o POST publicamente, adicionar protecao contra abuso por usuario/IP e limites globais de requisicoes.

**Importante:** a implementacao e experimental, ainda nao foi validada contra o VLR e nao deve ser publicada em producao antes desses testes. Nao ha garantia de atualizacao em ate 1 hora apos o termino real de series atrasadas.
