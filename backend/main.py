"""API experimental do Vava Comps: consulta campeonatos sob demanda, sem gerar JSONs."""
import os
import time
import threading
import re
from urllib.request import Request, urlopen
from urllib.parse import urljoin
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
EVENT_POOLS = {2766: ["Summit", "Abyss", "Split", "Ascent", "Haven", "Sunset", "Lotus"],
               2977: ["Summit", "Abyss", "Split", "Ascent", "Haven", "Sunset", "Lotus"]}
# Torneios anteriores com a mesma map pool; ampliar somente apos validacao.
FALLBACK_EVENTS = {2766: [2977]}
series_cache = {}
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
    # Estatisticas gerais: agrega partidas de torneios anteriores cadastrados, sem
    # misturar jogadores ou composicoes. O historico exibido e limitado no frontend.
    # Apenas fontes com map pool historica equivalente entram nesta consulta.
    if event_id in FALLBACK_EVENTS:
        current = response["equipes"].get(str(team_id), {})
        current_maps = current.get("mapas", [])
        latest = max(current_maps, key=lambda m: (m["data"], int(m["game_id"])), default=None)
        roster = {str(p["id"]) for p in latest["jogadores"]} if latest else set()
        if len(roster) == 5:
            seen = {str(m["game_id"]) for m in current_maps}
            for prior_id in FALLBACK_EVENTS[event_id]:
                try:
                    prior_index = event_index(prior_id)
                    if (not prior_index["map_pool_confirmada"]
                        or {m.lower() for m in prior_index["map_pool"]}
                           != {m.lower() for m in response["map_pool"]}):
                        continue
                    prior = event_team(prior_id, team_id)
                    candidates = prior["equipes"].get(str(team_id), {}).get("mapas", [])
                    for m in candidates:
                        if (str(m["game_id"]) in seen or m["data"] > latest["data"]
                            or {str(p["id"]) for p in m["jogadores"]} != roster):
                            continue
                        seen.add(str(m["game_id"]))
                        current_maps.append({**m, "origem_evento_id": prior_id,
                                             "origem_evento_nome": "VCT 2026: Americas Stage 2",
                                             "composicao_emprestada": True})
                except Exception as exc:
                    response["meta"]["erros"].append({"evento_anterior": prior_id,
                                                       "erro": str(exc)[:120]})
    with lock:
        cache[key] = (time.monotonic(), response)
    return response


# Eventos verificados no calendario VCT 2026 do VLR.gg.
REGIONAL_EVENTS = {
    "americas": [(2682, "Kickoff"), (2860, "Stage 1"), (2977, "Stage 2")],
    "pacific": [(2683, "Kickoff"), (2775, "Stage 1"), (2776, "Stage 2")],
    "emea": [(2684, "Kickoff"), (2863, "Stage 1"), (2976, "Stage 2")],
    "china": [(2685, "Kickoff"), (2864, "Stage 1"), (2978, "Stage 2")],
}
REGION_LABELS = {"americas": "Americas", "pacific": "Pacific",
                 "emea": "EMEA", "china": "China"}

def _region_events(region):
    events = REGIONAL_EVENTS.get(region.lower())
    if events is None:
        raise HTTPException(404, "Regiao nao cadastrada")
    return events

MASTERS_2026 = [(2760, "Masters Santiago"), (2765, "Masters London")]
CHAMPIONS_2026 = (2766, "Champions")

@app.get("/api/temporadas/2026/regioes/{region}/equipes")
def regional_teams(region: str):
    region_events = _region_events(region)
    calendar = [region_events[0], MASTERS_2026[0], region_events[1],
                MASTERS_2026[1], region_events[2], CHAMPIONS_2026]
    # Apenas tres indices regionais para montar a lista rapidamente.
    # Masters e Champions sao verificados somente apos selecionar a equipe.
    futures = {pool.submit(event_index, eid): (eid, label) for eid, label in region_events}
    indexes, errors = {}, []
    for future in as_completed(futures):
        eid, label = futures[future]
        try:
            indexes[eid] = future.result()
        except Exception as exc:
            errors.append({"evento": eid, "erro": str(exc)[:150]})
    teams = {}
    for eid, label in region_events:
        for team in indexes.get(eid, {}).get("equipes", []):
            key = str(team["team_id"])
            entry = teams.setdefault(key, {**team, "eventos": []})
            entry["eventos"].append({"id": eid, "nome": label})
    if not teams and errors:
        raise HTTPException(502, "Nao foi possivel consultar os eventos da regiao")
    return {"regiao": region, "temporada": 2026,
            "equipes": sorted(teams.values(), key=lambda t: t["nome"].lower()),
            "eventos": [{"id": eid, "nome": label} for eid, label in calendar],
            "meta": {"erros": errors}}

@app.get("/api/temporadas/2026/regioes/{region}/equipes/{team_id}/eventos")
def regional_team_events(region: str, team_id: int):
    region_events = _region_events(region)
    calendar = [region_events[0], MASTERS_2026[0], region_events[1],
                MASTERS_2026[1], region_events[2], CHAMPIONS_2026]
    futures = {pool.submit(event_index, eid): (eid, label) for eid, label in calendar}
    available = set()
    for future in as_completed(futures):
        eid, label = futures[future]
        try:
            if any(t["team_id"] == team_id for t in future.result()["equipes"]):
                available.add(eid)
        except Exception:
            continue
    return {"eventos": [{"id": eid, "nome": label} for eid, label in calendar
                        if eid in available]}

# Busca global no catalogo VCT 2026 e no GC Championship.
# Os indices ficam em cache; nenhuma serie detalhada e consultada aqui.
@app.get("/api/temporadas/2026/equipes/busca")
def search_season_teams(q: str = Query(..., min_length=2, max_length=80)):
    needle = q.strip().casefold()
    events = [(eid, region) for region, stages in REGIONAL_EVENTS.items()
              for eid, _ in stages]
    events += [(eid, "international") for eid, _ in MASTERS_2026]
    events += [(CHAMPIONS_2026[0], "international"), (3134, "gc")]
    futures = {pool.submit(event_index, eid): (eid, region) for eid, region in events}
    teams, errors = {}, []
    for future in as_completed(futures):
        eid, region = futures[future]
        try:
            index = future.result()
            for team in index["equipes"]:
                if needle not in team["nome"].casefold():
                    continue
                key = str(team["team_id"])
                entry = teams.setdefault(key, {**team, "regioes": [], "circuitos": []})
                if region not in ("international", "gc") and region not in entry["regioes"]:
                    entry["regioes"].append(region)
                circuit = "gc" if region == "gc" else "vct"
                if circuit not in entry["circuitos"]:
                    entry["circuitos"].append(circuit)
        except Exception as exc:
            errors.append({"evento": eid, "erro": str(exc)[:100]})
    return {"equipes": sorted(teams.values(), key=lambda t: t["nome"].casefold())[:60],
            "meta": {"erros": errors}}

@app.get("/api/temporadas/2026/equipes/{team_id}/eventos")
def team_season_events(team_id: int):
    if team_id <= 0:
        raise HTTPException(400, "Equipe invalida")
    events = [(eid, label, region) for region, stages in REGIONAL_EVENTS.items()
              for eid, label in stages]
    events += [(eid, label, "international") for eid, label in MASTERS_2026]
    events += [(CHAMPIONS_2026[0], CHAMPIONS_2026[1], "international")]
    futures = {pool.submit(event_index, eid): (eid, label, region) for eid, label, region in events}
    found = []
    for future in as_completed(futures):
        eid, label, region = futures[future]
        try:
            if any(t["team_id"] == team_id for t in future.result()["equipes"]):
                found.append({"id": eid, "nome": (REGION_LABELS[region] + " " + label)
                              if region in REGION_LABELS else label,
                              "regiao": region})
        except Exception:
            continue
    order = {eid: n for n, eid in enumerate(
        [2682, 2683, 2684, 2685, 2760, 2860, 2775, 2863, 2864,
         2765, 2977, 2776, 2976, 2978, 2766])}
    return {"eventos": sorted(found, key=lambda e: order.get(e["id"], 99))}

@app.get("/api/temporadas/2026/regioes/{region}/equipes/{team_id}")
def regional_team(region: str, team_id: int):
    events = _region_events(region)
    if team_id <= 0:
        raise HTTPException(400, "Equipe invalida")
    entries, errors = [], []
    for event_id, label in events:
        try:
            index = event_index(event_id)
            if not any(t["team_id"] == team_id for t in index["equipes"]):
                continue
            # Evita fallback de outros torneios: cada evento contribui somente
            # com suas partidas, sem duplicar os jogos entre stages.
            matches = [m for m in index["partidas"]
                       if any(t["team_id"] == team_id for t in m["equipes"])]
            futures = {pool.submit(_one_series, m, team_id): m["id"] for m in matches}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        entries.append((event_id, label, result))
                except Exception as exc:
                    errors.append({"serie": futures[future], "erro": str(exc)[:150]})
        except Exception as exc:
            errors.append({"evento": event_id, "erro": str(exc)[:150]})
    if not entries and errors:
        raise HTTPException(502, "Nao foi possivel consultar partidas desta equipe")
    result = {"regiao": region, "temporada": 2026, "equipes": {},
              "map_pool": [], "map_pool_confirmada": False,
              "meta": {"erros": errors}}
    seen = set()
    for event_id, label, item in entries:
        for tid, team in item.items():
            target = result["equipes"].setdefault(tid, {
                "team_id": team["team_id"], "nome": team["nome"], "mapas": []})
            for match in team["mapas"]:
                unique = (tid, str(match["game_id"]))
                if unique in seen:
                    continue
                seen.add(unique)
                target["mapas"].append({**match, "origem_evento_id": event_id,
                                         "origem_evento_nome": "VCT 2026: "
                                         + REGION_LABELS[region] + " " + label})
    # Nao presume uma map pool unica para toda a temporada.
    result["map_pool"] = sorted({m["mapa"] for t in result["equipes"].values()
                                 for m in t["mapas"]})
    return result

@app.get("/api/temporadas/2026/equipes/{team_id}/eventos/{event_id}")
def season_event_team(team_id: int, event_id: int):
    allowed = {eid for events in REGIONAL_EVENTS.values() for eid, _ in events}
    allowed.update(eid for eid, _ in MASTERS_2026)
    allowed.add(CHAMPIONS_2026[0])
    if event_id not in allowed:
        raise HTTPException(404, "Campeonato nao cadastrado na temporada")
    # Consulta isolada: nao inclui fallback de outro torneio.
    index = event_index(event_id)
    matches = [m for m in index["partidas"]
               if any(t["team_id"] == team_id for t in m["equipes"])]
    if not matches:
        raise HTTPException(404, "Equipe sem partidas neste campeonato")
    results, errors = [], []
    futures = {pool.submit(_one_series, m, team_id): m["id"] for m in matches}
    for future in as_completed(futures):
        try:
            value = future.result()
            if value:
                results.append(value)
        except Exception as exc:
            errors.append({"serie": futures[future], "erro": str(exc)[:150]})
    response = {"event_id": event_id, "equipes": {},
                "map_pool": index["map_pool"],
                "map_pool_confirmada": index["map_pool_confirmada"],
                "meta": {"erros": errors}}
    for item in results:
        for tid, team in item.items():
            target = response["equipes"].setdefault(tid, {
                "team_id": team["team_id"], "nome": team["nome"], "mapas": []})
            target["mapas"].extend(team["mapas"])
    if not response["map_pool"]:
        response["map_pool"] = sorted({m["mapa"] for t in response["equipes"].values()
                                       for m in t["mapas"]})
    return response

logo_cache = {}

@app.get("/api/equipes/{team_id}/logo")
def team_logo(team_id: int):
    if not 1 <= team_id <= 9999999:
        raise HTTPException(400, "Equipe invalida")
    with lock:
        if team_id in logo_cache:
            return {"url": logo_cache[team_id]}
    try:
        req = Request(f"https://www.vlr.gg/team/{team_id}/",
                      headers={"User-Agent": "Mozilla/5.0 (compatible; VavaComps/1.0)"})
        with urlopen(req, timeout=8) as response:
            html = response.read(300000).decode("utf-8", errors="replace")
        # A imagem principal da equipe aparece dentro de team-header-logo.
        match = re.search(r'team-header-logo[\\s\\S]{0,900}?<img[^>]*src=["\\\']([^"\\\']+)', html, re.I)
        url = urljoin("https://www.vlr.gg/", match.group(1)) if match else None
        if url and not url.startswith(("https://owcdn.net/", "https://www.vlr.gg/")):
            url = None
    except Exception:
        url = None
    with lock:
        logo_cache[team_id] = url
    return {"url": url}

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
