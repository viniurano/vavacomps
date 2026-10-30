"""Auditoria offline do armazenamento V4. Nao importa backend.main nem acessa rede."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "dados" / "v4"
CATALOG = STORE / "catalogo_2026.json"

def catalog():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    events = data["events"]
    ids = [int(e["event_id"]) for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs duplicados no catalogo")
    return events

def ensure_event_files():
    """Cria somente arquivos inexistentes. Nunca altera snapshots existentes."""
    from backend.v4_store import _write
    created = []
    for event in catalog():
        eid = int(event["event_id"])
        path = STORE / "eventos" / f"{eid}.json"
        if not path.exists():
            _write(path, {"event_id": eid, "equipes": {}, "series": {}, "meta": {"status": "aguardando_dados", "fonte": "catalogo_local"}})
            created.append(eid)
    return created

def audit():
    result = {"eventos_cadastrados": 0, "eventos_com_mapas": 0, "mapas_registrados": 0,
              "jogos_unicos": 0, "problemas": [], "eventos": []}
    for event in catalog():
        eid = int(event["event_id"])
        path = STORE / "eventos" / f"{eid}.json"
        row = {"event_id": eid, "regiao": event["region"], "nome": event["name"],
               "equipes": 0, "mapas_registrados": 0, "jogos_unicos": 0,
               "series_unicas": 0, "status": "sem_arquivo"}
        if not path.exists():
            result["eventos"].append(row)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data["event_id"]) != eid:
                raise ValueError("event_id do arquivo nao corresponde ao catalogo")
            teams = data.get("equipes", {})
            if not isinstance(teams, dict):
                raise ValueError("equipes nao e um objeto")
            row["equipes"] = len(teams)
            games, series = set(), set()
            for tid, team in teams.items():
                seen = set()
                for m in team.get("mapas", []):
                    gid = m.get("game_id")
                    if gid is None:
                        result["problemas"].append(f"{eid}/{tid}: mapa sem game_id")
                        continue
                    if str(gid) in seen:
                        result["problemas"].append(f"{eid}/{tid}: game_id duplicado {gid}")
                    seen.add(str(gid))
                    games.add(str(gid))
                    if m.get("serie_id") is not None:
                        series.add(str(m["serie_id"]))
                    row["mapas_registrados"] += 1
            row["jogos_unicos"] = len(games)
            row["series_unicas"] = len(series)
            row["status"] = "dados_parciais" if games else "aguardando_dados"
            result["mapas_registrados"] += row["mapas_registrados"]
            result["jogos_unicos"] += len(games)
            if games:
                result["eventos_com_mapas"] += 1
        except (OSError, ValueError, TypeError, KeyError) as exc:
            row["status"] = "erro"
            result["problemas"].append(f"{eid}: {exc}")
        result["eventos"].append(row)
    result["eventos_cadastrados"] = len(result["eventos"])
    return result

if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
