"""API experimental do Vava Comps: consulta campeonatos sob demanda, sem gerar JSONs."""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from vlrdevapi import VLRClient

app = FastAPI(title="Vava Comps API", version="3.1.0")
origins = [s.strip() for s in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if s.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])
CACHE_TTL = 1800
MAX_SERIES = 120
cache = {}
lock = threading.Lock()
pool = ThreadPoolExecutor(max_workers=4)
# Pool confirmada para o Champions 2026; outros eventos exigem cadastro/validacao.
EVENT_POOLS = {2766: ["Summit", "Abyss", "Split", "Ascent", "Haven", "Sunset", "Lotus"],\n               2977: ["Summit", "Abyss", "Split", "Ascent", "Haven", "Sunset", "Lotus"]}
# Torneios anteriores com a mesma map pool; ampliar somente apos validacao.\nFALLBACK_EVENTS = {2766: [2977]}\nseries_cache = {}
event_index_cache = {}

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


def _obj(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value if isinstance(value, dict) else {}

def _team(value):
    d = _obj(value)
    if not d:
        return None
    ident = d.get("team_id") or d.get("id")
    name = d.get("team_name") or d.get("name")
    if ident is None or not name:
        return None
    return {"team_id": int(ident), "nome": str(name)}

def _match_teams(match):
    d = _obj(match)
    teams = [_team(d.get(k)) for k in ("team1", "team2")]
    if all(teams):
        return teams
    pair = d.get("teams")
    if isinstance(pair, list) and len(pair) >= 2:
        teams = [_team(x) for x in pair[:2]]
    return teams if all(teams) else []

def event_index(event_id):
    with lock:
        item = event_index_cache.get(event_id)
        if item and time.monotonic() - item[0] < CACHE_TTL:
            return item[1]
    with VLRClient() as client:
        matches = client.event(event_id).matches().matches
    completed = [m for m in matches if getattr(m.status, "value", None) == "completed"]
    if len(completed) > MAX_SERIES:
        raise ValueError("Campeonato grande demais para esta versao")
    teams = {}
    indexed = []
    for m in completed:
        pair = _match_teams(m)
        for t in pair:
            teams[str(t["team_id"])] = t
        indexed.append({"id": int(m.match_id), "data": m.match_date.isoformat(), "equipes": pair})
    result = {"event_id": event_id, "equipes": sorted(teams.values(), key=lambda x: x["nome"].lower()),
              "partidas": indexed, "map_pool": EVENT_POOLS.get(event_id, []),
              "map_pool_confirmada": event_id in EVENT_POOLS}
    with lock:
        event_index_cache[event_id] = (time.monotonic(), result)
    return result

def _series_data(match_id):
    with lock:
        item = series_cache.get(match_id)
        if item and time.monotonic() - item[0] < CACHE_TTL:
            return item[1]
    with VLRClient() as client:
        series = client.series(match_id)
        value = (series.info(), series.players())
    with lock:
        series_cache[match_id] = (time.monotonic(), value)
    return value

def _one_series(item, team_id):
    info, data = _series_data(item["id"])
    if str(team_id) not in (str(info.team1.id), str(info.team2.id)):
        return None
    result = {"equipes": {}}
    for game in info.games:
        if not game.played:
            continue
        map_data = next((m for m in data.maps if str(m.game_id) == str(game.game_id)), None)
        if map_data is None:
            continue
        if str(map_data.team1.team_id) == str(info.team1.id):
            first, second = map_data.team1, map_data.team2
        elif str(map_data.team2.team_id) == str(info.team1.id):
            first, second = map_data.team2, map_data.team1
        else:
            continue
        salvar_equipe(result, first, second, game, info, item["data"], True)
        salvar_equipe(result, second, first, game, info, item["data"], False)
    return result["equipes"]

@app.get("/api/eventos/{event_id}/equipes")
def list_event_teams(event_id: int):
    if not 1 <= event_id <= 9999999:
        raise HTTPException(400, "ID de campeonato invalido")
    try:
        return event_index(event_id)
    except Exception as exc:
        raise HTTPException(502, f"Falha ao listar equipes: {type(exc).__name__}: {str(exc)[:100]}") from exc

@app.get("/api/eventos/{event_id}/equipes/{team_id}")
def event_team(event_id: int, team_id: int):
    if not 1 <= event_id <= 9999999 or team_id <= 0:
        raise HTTPException(400, "ID invalido")
    key = (event_id, team_id)
    with lock:
        item = cache.get(key)
        if item and time.monotonic() - item[0] < CACHE_TTL:
            return item[1]
    index = event_index(event_id)
    matches = [m for m in index["partidas"] if any(t["team_id"] == team_id for t in m["equipes"])]
    if not matches:
        raise HTTPException(404, "Equipe sem partidas identificadas neste campeonato")
    results, errors = [], []
    futures = {pool.submit(_one_series, m, team_id): m["id"] for m in matches}
    for future in as_completed(futures):
        try:
            value = future.result()
            if value:
                results.append(value)
        except Exception as exc:
            errors.append({"serie_id": futures[future], "erro": str(exc)[:150]})
    team = next((t for t in index["equipes"] if t["team_id"] == team_id), None)
    response = {"event_id": event_id, "equipes": {}, "map_pool": index["map_pool"],
                "map_pool_confirmada": index["map_pool_confirmada"], "meta": {"erros": errors}}
    for result in results:
        for tid, entry in result.items():
            if str(tid) == str(team_id) or any(m["adversario_id"] == team_id for m in entry["mapas"]):
                target = response["equipes"].setdefault(tid, {"team_id": entry["team_id"], "nome": entry["nome"], "mapas": []})
                target["mapas"].extend(entry["mapas"])
    if team and str(team_id) not in response["equipes"]:
        response["equipes"][str(team_id)] = {"team_id": team_id, "nome": team["nome"], "mapas": []}
    if not response["map_pool"]:
        response["map_pool"] = sorted({m["mapa"] for e in response["equipes"].values() for m in e["mapas"]})
    # Preenche somente mapas ausentes com partidas anteriores, exigindo o MESMO quinteto
    # (IDs dos jogadores) e a MESMA map pool. Nunca mistura elencos distintos.
    if event_id in FALLBACK_EVENTS:
        current = response["equipes"].get(str(team_id), {})
        current_maps = current.get("mapas", [])
        played = {m["mapa"].lower() for m in current_maps}
        missing = {m.lower() for m in response["map_pool"]} - played
        latest = max(current_maps, key=lambda m: (m["data"], int(m["game_id"])), default=None)
        roster = {p["id"] for p in latest["jogadores"]} if latest else set()
        if missing and len(roster) == 5:
            for prior_id in FALLBACK_EVENTS[event_id]:
                try:
                    prior_index = event_index(prior_id)
                    # Exige a mesma pool explicitamente confirmada, nao apenas mapas jogados.
                    if not prior_index["map_pool_confirmada"] or {m.lower() for m in prior_index["map_pool"]} != {m.lower() for m in response["map_pool"]}:
                        continue
                    prior = event_team(prior_id, team_id)
                    candidates = prior["equipes"].get(str(team_id), {}).get("mapas", [])
                    for map_name in list(missing):
                        options = [m for m in candidates if m["mapa"].lower() == map_name
                                   and m["data"] <= latest["data"]
                                   and {p["id"] for p in m["jogadores"]} == roster]
                        if options:
                            chosen = max(options, key=lambda m: (m["data"], int(m["game_id"])))
                            current_maps.append({**chosen, "origem_evento_id": prior_id,
                                                 "origem_evento_nome": "VCT 2026: Americas Stage 2",
                                                 "composicao_emprestada": True})
                            missing.remove(map_name)
                    if not missing:
                        break
                except Exception as exc:
                    response["meta"]["erros"].append({"evento_anterior": prior_id, "erro": str(exc)[:120]})
    with lock:
        cache[key] = (time.monotonic(), response)
    return response

@app.get("/api/health")
def health():
    return {"status": "ok", "versao": "3.1.0"}

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
