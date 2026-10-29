"""API experimental do Vava Comps: consulta campeonatos sob demanda, sem gerar JSONs."""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from vlrdevapi import VLRClient

app = FastAPI(title="Vava Comps API", version="3.0.0")
origins = [s.strip() for s in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if s.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])
CACHE_TTL = 1800
MAX_SERIES = 120
cache = {}
lock = threading.Lock()
pool = ThreadPoolExecutor(max_workers=3)

def salvar_equipe(result, team, opponent, game, info, date, first):
    players = [{"nome": p.name, "id": p.player_id, "agente": p.agents[0],
                "stats": p.stats.model_dump(mode="json")}
               for p in team.players if p.agents]
    if len(players) != 5:
        return
    team_id = str(team.team_id)
    entry = result["equipes"].setdefault(team_id, {
        "team_id": team.team_id, "nome": team.team_name, "mapas": []})
    points = game.team1_score if first else game.team2_score
    enemy_points = game.team2_score if first else game.team1_score
    entry["mapas"].append({
        "serie_id": info.series_id, "game_id": game.game_id,
        "mapa": game.map_name, "adversario": opponent.team_name,
        "adversario_id": opponent.team_id, "data": date,
        "placar": [points, enemy_points], "vitoria": points > enemy_points,
        "rounds_ataque": game.team1_attack_rounds if first else game.team2_attack_rounds,
        "rounds_defesa": game.team1_defense_rounds if first else game.team2_defense_rounds,
        "jogadores": players, "composicao": sorted(p["agente"] for p in players)
    })

def collect_event(event_id):
    result = {"campeonato": f"Evento VLR {event_id}", "event_id": event_id, "equipes": {}}
    errors = []
    with VLRClient() as client:
        matches = client.event(event_id).matches().matches
        completed = [m for m in matches if getattr(m.status, "value", None) == "completed"]
        if len(completed) > MAX_SERIES:
            raise ValueError(f"Campeonato grande demais para esta versao ({len(completed)} series).")
        for match in completed:
            try:
                series = client.series(match.match_id)
                info, data = series.info(), series.players()
                for game in info.games:
                    if not game.played:
                        continue
                    map_data = next((m for m in data.maps if str(m.game_id) == str(game.game_id)), None)
                    if map_data is None:
                        continue
                    # Atribui lados pelo ID, nao pela ordem retornada no endpoint de jogadores.
                    if str(map_data.team1.team_id) == str(info.team1.id):
                        first, second = map_data.team1, map_data.team2
                    elif str(map_data.team2.team_id) == str(info.team1.id):
                        first, second = map_data.team2, map_data.team1
                    else:
                        raise ValueError("IDs das equipes nao correspondem")
                    date = match.match_date.isoformat()
                    salvar_equipe(result, first, second, game, info, date, True)
                    salvar_equipe(result, second, first, game, info, date, False)
            except Exception as exc:
                errors.append({"serie_id": match.match_id, "erro": str(exc)[:180]})
    result["meta"] = {"series_concluidas": len(completed), "erros": errors}
    return result

@app.get("/api/health")
def health():
    return {"status": "ok", "versao": "3.0.0"}

@app.get("/api/eventos/{event_id}")
def event_data(event_id: int, refresh: bool = Query(False)):
    if not 1 <= event_id <= 9999999:
        raise HTTPException(400, "ID de campeonato invalido")
    now = time.monotonic()
    with lock:
        item = cache.get(event_id)
        if item and not refresh and now - item[0] < CACHE_TTL:
            return item[1]
    try:
        # Timeout limita a espera HTTP; o trabalho em execucao pode continuar no servidor.
        result = pool.submit(collect_event, event_id).result(timeout=110)
    except Exception as exc:
        raise HTTPException(502, f"Nao foi possivel consultar o VLR: {type(exc).__name__}") from exc
    with lock:
        cache[event_id] = (time.monotonic(), result)
    return result
