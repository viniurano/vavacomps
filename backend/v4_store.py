"""V4: armazenamento persistente e coleta agendada por serie.
Execute: python -m backend.v4_store schedule | run
O site nunca depende de uma consulta ao VLR para ler dados ja salvos.
"""
import json
import os
import re
import time
import threading
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "dados" / "v4"
TZ = ZoneInfo("America/Sao_Paulo")
GUARD = threading.RLock()
MIN_INTERVAL = 15 * 60
_last = {}
_inflight = set()

def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default

def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)

def _event_path(event_id):
    return STORE / "eventos" / (str(int(event_id)) + ".json")

def event_data(event_id):
    return _read(_event_path(event_id), {"event_id": int(event_id), "equipes": {}, "series": {}, "meta": {}})

def get_team(event_id, team_id):
    data = event_data(event_id)
    return data["equipes"].get(str(team_id))

def _merge_series(event_id, series_id, entries, date):
    with GUARD:
        data = event_data(event_id)
        for tid, team in entries.items():
            target = data["equipes"].setdefault(str(tid), {"team_id": team["team_id"], "nome": team["nome"], "mapas": []})
            target["nome"] = team["nome"]
            old = {str(m["game_id"]): m for m in target["mapas"]}
            for m in team["mapas"]:
                old[str(m["game_id"])] = m
            target["mapas"] = sorted(old.values(), key=lambda m: (m.get("data",""), int(m["game_id"])))
        data["series"][str(series_id)] = {"ultima_coleta": datetime.now(timezone.utc).isoformat(), "data": date}
        data["meta"]["ultima_atualizacao"] = datetime.now(timezone.utc).isoformat()
        _write(_event_path(event_id), data)

def collect_series(event_id, series_id, force=False):
    """Uma serie atualiza as duas equipes. Protecao compartilhada por processo."""
    key = (int(event_id), int(series_id))
    with GUARD:
        now = time.monotonic()
        if key in _inflight:
            return {"status": "em_andamento", "serie_id": series_id}
        if not force and now - _last.get(key, -1e12) < MIN_INTERVAL:
            return {"status": "intervalo", "serie_id": series_id}
        _inflight.add(key)
        _last[key] = now
    try:
        # Import tardio evita dependencias circulares com a API.
        from backend.main import _one_series
        item = {"id": int(series_id), "data": datetime.now(TZ).date().isoformat()}
        entries = _one_series(item, None)
        if not entries or not any(t.get("mapas") for t in entries.values()):
            return {"status": "sem_mapas", "serie_id": series_id}
        _merge_series(event_id, series_id, entries, item["data"])
        return {"status": "atualizado", "serie_id": series_id, "mapas": sum(len(t["mapas"]) for t in entries.values()) // 2}
    finally:
        with GUARD:
            _inflight.discard(key)

def refresh_team(event_id, team_id, discover):
    """Atualiza apenas as series do time selecionado, nunca todo o evento."""
    key = ("team", int(event_id), int(team_id))
    with GUARD:
        now = time.monotonic()
        if key in _inflight or now - _last.get(key, -1e12) < MIN_INTERVAL:
            return {"status": "intervalo", "aguarde_segundos": max(0, round(MIN_INTERVAL - (now - _last.get(key, now))))}
        _inflight.add(key)
        _last[key] = now
    try:
        matches = discover(event_id, team_id)
        results = []
        for match in matches:
            try:
                results.append(collect_series(event_id, match["id"]))
            except Exception as exc:
                results.append({"serie_id": match["id"], "status": "erro", "erro": str(exc)[:160]})
                if "429" in str(exc):
                    break
            time.sleep(2)
        return {"status": "concluido", "series": results}
    finally:
        with GUARD:
            _inflight.discard(key)

class CalendarParser(HTMLParser):
    """Extrai cards /match/ do calendario VLR; horarios sao timestamps UTC do HTML."""
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.card = None
        self.cards = {}
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and re.search(r"/(\d+)/[^/]*", a.get("href", "")) and "match-item" in a.get("class", ""):
            match = re.search(r"/(\d+)/", a["href"])
            if match:
                self.card = {"serie_id": int(match.group(1)), "timestamp": None, "equipes": [], "evento": "", "evento_id": None}
                self.depth = 0
        if self.card is not None:
            event_link = re.search(r"/event/(\d+)", a.get("href", ""))
            if event_link:
                self.card["evento_id"] = int(event_link.group(1))
            self.depth += 1
            for attr in ("data-utc-ts", "data-ts"):
                raw = a.get(attr)
                if raw and raw.isdigit():
                    self.card["timestamp"] = int(raw)
            if "match-item-vs-team-name" in a.get("class", ""):
                self._team = True
            if "match-item-event" in a.get("class", ""):
                self._event = True
    def handle_data(self, data):
        if self.card is not None:
            value = data.strip()
            if value and getattr(self, "_team", False):
                self.card["equipes"].append(value)
                self._team = False
            if value and getattr(self, "_event", False):
                self.card["evento"] = value
                self._event = False
    def handle_endtag(self, tag):
        if self.card is not None:
            self.depth -= 1
            if self.depth <= 0:
                if self.card["timestamp"]:
                    self.cards[self.card["serie_id"]] = self.card
                self.card = None
                self._team = self._event = False

def schedule_today():
    """Uma consulta diaria ao calendario; nunca consulta detalhes das series."""
    req = Request("https://www.vlr.gg/matches/", headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as response:
        html = response.read(2500000).decode("utf-8", "replace")
    parser = CalendarParser()
    parser.feed(html)
    today = datetime.now(TZ).date()
    known = _read(STORE / "agenda.json", {"partidas": {}})
    # A associacao evento/serie sera validada na coleta pelo indice de eventos.
    for mid, card in parser.cards.items():
        started = datetime.fromtimestamp(card["timestamp"], timezone.utc)
        if started.astimezone(TZ).date() != today:
            continue
        entry = known["partidas"].get(str(mid), {})
        entry.update({"serie_id": mid, "inicio_utc": started.isoformat(),
                      "equipes": card["equipes"], "campeonato": card["evento"],
                      "evento_id": card.get("evento_id"),
                      "consultas_utc": [(started + timedelta(hours=h)).isoformat() for h in (2, 3)],
                      "executadas": entry.get("executadas", [])})
        known["partidas"][str(mid)] = entry
    known["ultima_consulta"] = datetime.now(timezone.utc).isoformat()
    _write(STORE / "agenda.json", known)
    return {"partidas_no_dia": sum(datetime.fromisoformat(p["inicio_utc"]).astimezone(TZ).date() == today for p in known["partidas"].values()),
            "novos_cards": len(parser.cards)}

def run_due(resolve_event=None):
    agenda = _read(STORE / "agenda.json", {"partidas": {}})
    now = datetime.now(timezone.utc)
    results = []
    for item in agenda["partidas"].values():
        for planned in item.get("consultas_utc", []):
            if planned in item.get("executadas", []) or datetime.fromisoformat(planned) > now:
                continue
            event_id = (resolve_event(item) if resolve_event else item.get("evento_id"))
            if not event_id:
                results.append({"serie_id": item["serie_id"], "status": "evento_nao_identificado"})
                continue
            try:
                result = collect_series(event_id, item["serie_id"])
                results.append(result)
                if result["status"] in ("atualizado", "sem_mapas", "intervalo"):
                    item.setdefault("executadas", []).append(planned)
                if "429" in str(result):
                    break
            except Exception as exc:
                results.append({"serie_id": item["serie_id"], "erro": str(exc)[:120]})
                if "429" in str(exc):
                    _write(STORE / "agenda.json", agenda)
                    return results
            time.sleep(2)
    _write(STORE / "agenda.json", agenda)
    return results

if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "schedule":
        print(json.dumps(schedule_today(), ensure_ascii=False))
    elif action == "run":
        print(json.dumps(run_due(), ensure_ascii=False))
    else:
        raise SystemExit("Uso: python -m backend.v4_store schedule | run")
