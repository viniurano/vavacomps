# Vava Comps API (experimental)

API Python para consultar campeonatos do VLR sob demanda, sem gravar JSONs por evento.

## Executar localmente

Na raiz do projeto:

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 8001
```

Teste: http://127.0.0.1:8001/api/health

Champions 2026: http://127.0.0.1:8001/api/eventos/2766

GC Championship 2026: http://127.0.0.1:8001/api/eventos/3134

O primeiro carregamento de um evento pode demorar. O cache e em memoria por 30 minutos e desaparece ao reiniciar o servidor. O limite experimental e 120 series concluidas por evento. Nao ha ainda busca por nome, integracao ao HTML nem deploy.

CORS_ORIGINS configura origens permitidas, separadas por virgulas. O endpoint refresh e experimental e nao deve ser exposto sem controle de acesso em producao.
