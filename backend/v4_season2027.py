"""Sincronizacao automatica VCT 2027: eventos, participantes, agenda e resultados."""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from vlrdevapi import VLRClient
from backend import v4_store
from backend.main import participant_index, _match_teams

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "dados" / "v4"
CATALOG = STORE / "catalogo.json"
SEASON = STORE / "temporadas" / "2027.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def competition(name):
    value = name.casefold()
    if "last chance" in value or re.search(r"\blcq\b", value):
        return "lcq"
    if "qualifier playoff" in value:
        return "qualifiers"
    if "kickoff" in value:
        return "kickoff"
    if "masters" in value:
        return "masters"
    if "champions" in value:
        return "champions"
    if "stage 1" in value or "cup 1" in value or "cups 1" in value:
        return "stage_1"
    if "stage 2" in value or "cup 2" in value or "cups 2" in value:
        return "stage_2"
    return None


def eligible(event):
    name = str(event.get("name", ""))
    value = name.casefold()
    if int(event.get("year") or 0) != 2027 or event.get("tier") != "vct":
        return False
    if not (value.startswith("vct 2027") or "valorant champions tour 2027" in value):
        return False
    kind = competition(name)
    if not kind:
        return False
    region = str(event.get("region") or "").casefold()
    if kind in ("qualifiers", "lcq"):
        if region == "china":
            return False
        if kind == "qualifiers":
            return "qualifier playoff" in value
        return True
    return True


def subregion(name):
    value = name.casefold()
    rules = [
        (("brazil", "brasil"), "brazil"),
        (("latam north", "latam south", "latam"), "latam"),
        (("north america", "north-america"), "north_america"),
        (("europe",), "europe"),
        (("turkiye", "türkiye", "turkey"), "turkey"),
        (("mena", "middle east", "africa"), "mea"),
        (("japan",), "japan"), (("korea",), "korea"),
        (("south asia",), "south_asia"),
        (("southeast asia", "sea", "indonesia", "thailand", "vietnam", "oceania"), "southeast_asia"),
        (("china",), "china"),
    ]
    for tokens, result in rules:
        if any(token in value for token in tokens):
            return result
    return None


def event_status(event):
    value = str(event.get("status") or "").casefold()
    return value if value in ("upcoming", "ongoing", "completed") else "discovered"


def match_status(match):
    value = getattr(getattr(match, "status", None), "value", None)
    return str(value if value is not None else getattr(match, "status", "unknown")).casefold()


def match_date(match):
    value = getattr(match, "match_date", None)
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def sync_event(event, season, report):
    event_id = int(event["event_id"])
    name = event["name"]
    region = str(event.get("region") or "unknown").casefold()
    kind = competition(name)
    sub = subregion(name)
    path = STORE / "eventos" / (str(event_id) + ".json")
    saved = v4_store.event_data(event_id)
    saved.setdefault("equipes", {})
    saved.setdefault("series", {})
    saved.setdefault("meta", {})

    # Evento concluido recebe uma ultima coleta; depois deixa de ser consultado.
    if event_status(event) == "completed" and saved["meta"].get("status_catalogo") == "completed":
        report["ignorados_finalizados"].append(event_id)
        return

    participants = []
    try:
        participants = participant_index(event_id).get("equipes", [])
    except Exception as exc:
        report["avisos"].append({"event_id": event_id, "etapa": "participantes", "erro": str(exc)[:140]})

    for team in participants:
        tid = str(team.get("team_id", ""))
        if not tid.isdigit():
            continue
        old = saved["equipes"].get(tid, {})
        saved["equipes"][tid] = {
            **old, "team_id": int(tid), "nome": team.get("nome") or old.get("nome") or tid,
            "logo": team.get("logo") or old.get("logo"), "mapas": old.get("mapas", []),
        }

    matches = {}
    counts = {"agendadas": 0, "concluidas": 0, "coletadas": 0}
    with VLRClient() as client:
        vlr_matches = client.event(event_id).matches().matches
        for match in vlr_matches:
            mid = int(match.match_id)
            status = match_status(match)
            date = match_date(match)
            teams = _match_teams(match)
            matches[str(mid)] = {
                "serie_id": mid, "data": date, "status": status,
                "equipes": teams, "url": "https://www.vlr.gg/" + str(mid),
            }
            if status == "completed":
                counts["concluidas"] += 1
                if str(mid) not in saved["series"]:
                    try:
                        result = v4_store.collect_series(
                            event_id, mid, force=True, match_date=(date or now())[:10]
                        )
                        if result.get("status") == "atualizado":
                            counts["coletadas"] += 1
                    except Exception as exc:
                        report["avisos"].append({"event_id": event_id, "serie_id": mid,
                                                 "erro": str(exc)[:140]})
                    time.sleep(1.0)
            else:
                counts["agendadas"] += 1

    saved = v4_store.event_data(event_id)
    saved.setdefault("equipes", {})
    for team in participants:
        tid = str(team.get("team_id", ""))
        if tid.isdigit():
            target = saved["equipes"].setdefault(tid, {
                "team_id": int(tid), "nome": team.get("nome") or tid, "mapas": []
            })
            target["nome"] = team.get("nome") or target.get("nome") or tid
            if team.get("logo"):
                target["logo"] = team["logo"]
    saved["partidas"] = matches
    saved.setdefault("meta", {}).update({
        "fonte": "VLR.gg", "temporada": 2027, "nome_evento": name,
        "regiao": region, "subregiao": sub, "ultima_sincronizacao": now(),
        "status_catalogo": event_status(event),
    })
    v4_store._write(path, saved)

    record = {
        "id": event_id, "event_id": event_id, "name": name, "nome": name,
        "competition": kind, "region": region, "subregion": sub,
        "status": event_status(event), "url": event.get("url"),
        "scope": event.get("scope"), "last_sync_at": now(),
        "teams_count": len(participants) or len(saved["equipes"]),
        "matches_count": len(matches),
    }
    by_event = {int(e["id"]): e for e in season.get("events", []) if e.get("id") is not None}
    by_event[event_id] = record
    season["events"] = sorted(by_event.values(), key=lambda e: (
        e.get("competition", ""), e.get("region", ""), e.get("subregion") or "", e.get("name", "")
    ))

    event_team_ids = set(saved["equipes"])
    team_map = {int(t["team_id"]): t for t in season.get("teams", []) if t.get("team_id") is not None}
    for tid in event_team_ids:
        team = saved["equipes"][tid]
        team_id = int(team.get("team_id") or tid)
        old = team_map.get(team_id, {})
        event_ids = set(int(x) for x in old.get("events", []))
        event_ids.add(event_id)
        team_map[team_id] = {
            **old, "team_id": team_id, "name": team.get("nome") or str(team_id),
            "region": region if region != "unknown" else old.get("region"),
            "subregion": sub or old.get("subregion"), "events": sorted(event_ids),
        }
    season["teams"] = sorted(team_map.values(), key=lambda t: t.get("name", "").casefold())
    report["eventos"].append({
        "event_id": event_id, "nome": name, "equipes": len(participants),
        "partidas": counts,
    })


def sync_season():
    catalog = read(CATALOG, {})
    season = read(SEASON, {})
    if int(season.get("year") or 0) != 2027:
        raise ValueError("Configuracao VCT 2027 ausente ou invalida")
    selected = [e for e in catalog.get("events", []) if eligible(e)]
    if not selected:
        raise ValueError("Nenhum evento VCT 2027 elegivel; arquivos anteriores preservados")
    report = {"eventos_detectados": len(selected), "eventos": [],
              "avisos": [], "ignorados_finalizados": []}
    for event in selected:
        try:
            sync_event(event, season, report)
        except Exception as exc:
            report["avisos"].append({"event_id": event.get("event_id"),
                                     "etapa": "evento", "erro": str(exc)[:160]})
    season["status"] = "active"
    season["last_sync_at"] = now()
    season["notes"] = (
        "Sincronizacao automatica via VLR.gg. Open Qualifiers ignorados; "
        "Qualifier Playoffs e LCQ incluidos em Americas, EMEA e Pacific; "
        "classificatorias da China ignoradas. Partidas, participantes e resultados "
        "sao atualizados incrementalmente."
    )
    v4_store._write(SEASON, season)
    report["equipes_na_temporada"] = len(season.get("teams", []))
    report["ultima_sincronizacao"] = season["last_sync_at"]
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    sync_season()
