"""Descoberta automatica dos principais eventos do VLR.gg.

Mantem um catalogo historico append-only: eventos antigos nunca sao removidos.
Apenas eventos VCT, Challengers/VCL e Game Changers entram no catalogo.
"""
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "dados" / "v4"
CATALOG = STORE / "catalogo.json"
LEGACY_CATALOG = STORE / "catalogo_2026.json"
EVENTS_URL = "https://www.vlr.gg/events/?region=all&tier=all"
MAIN_EVENT = re.compile(
    r"\b(vct|valorant champions|valorant masters|game changers|challengers|vcl)\b",
    re.I,
)

def _now():
    return datetime.now(timezone.utc).isoformat()

def _name_from_slug(slug):
    """Gera nome legivel a partir do slug, sem incorporar metadados do card."""
    value = re.sub(r"[-_]+", " ", slug).strip()
    replacements = (
        (r"\\bgame changers\\b", "Game Changers"),
        (r"\\bvalorant champions\\b", "Valorant Champions"),
        (r"\\bvalorant masters\\b", "Valorant Masters"),
        (r"\\bvct\\b", "VCT"),
        (r"\\bvcl\\b", "VCL"),
        (r"\\bemea\\b", "EMEA"),
        (r"\\bna\\b", "NA"),
        (r"\\blatam\\b", "LATAM"),
        (r"\\bamericas\\b", "Americas"),
        (r"\\bpacific\\b", "Pacific"),
        (r"\\bchina\\b", "China"),
    )
    value = value.title()
    for pattern, label in replacements:
        value = re.sub(pattern, label, value, flags=re.I)
    return value

def _tier(name):
    value = name.casefold()
    if "game changers" in value:
        return "game_changers"
    if "challengers" in value or re.search(r"\bvcl\b", value):
        return "challengers"
    return "vct"

def _region(name):
    value = name.casefold()
    for token, label in (("americas", "americas"), ("america", "americas"),
                         ("pacific", "pacific"), ("emea", "emea"),
                         ("china", "china"), ("brazil", "americas"),
                         ("latam", "americas"), ("north america", "americas")):
        if token in value:
            return label
    return "international" if any(x in value for x in
        ("masters", "champions", "international")) else "unknown"

def _status(text, classes):
    value = (text + " " + " ".join(classes)).casefold()
    if re.search(r"\b(completed|finished|concluded)\b|mod-completed", value):
        return "completed"
    if re.search(r"\b(ongoing|live|in progress)\b|mod-ongoing", value):
        return "ongoing"
    if re.search(r"\b(upcoming|starts in)\b|mod-upcoming", value):
        return "upcoming"
    return "discovered"

class EventListParser(HTMLParser):
    """Captura links /event/ID/slug e tenta ler o status do card mais proximo."""
    CARD_CLASSES = ("event-item", "event-card", "wf-card", "event-wrapper")

    def __init__(self):
        super().__init__()
        self.stack = []
        self.events = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        frame = {"tag": tag, "classes": classes, "text": "", "candidates": []}
        self.stack.append(frame)

        href = attrs.get("href", "")
        match = re.match(r"^/event/(\d+)/([^/?#]+)", href)
        if tag == "a" and match:
            candidate = {
                "event_id": int(match.group(1)),
                "slug": match.group(2),
                "anchor_title": attrs.get("title") or attrs.get("aria-label") or "",
            }
            frame["event_candidate"] = candidate
            target = None
            for parent in reversed(self.stack[:-1]):
                if any(any(token in cls.casefold() for token in self.CARD_CLASSES)
                       for cls in parent["classes"]):
                    target = parent
                    break
            if target is None and len(self.stack) > 1:
                target = self.stack[-2]
            if target is not None:
                target["candidates"].append(candidate)
            else:
                self._save(candidate, "", [])

    def handle_data(self, data):
        value = data.strip()
        if value:
            for frame in self.stack:
                frame["text"] += " " + value

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i]["tag"] == tag), None)
        if index is None:
            return
        closed = self.stack[index:]
        del self.stack[index:]
        for frame in closed:
            if frame.get("event_candidate") and not frame["event_candidate"]["anchor_title"]:
                frame["event_candidate"]["anchor_title"] = frame["text"]
            for candidate in frame["candidates"]:
                self._save(candidate, frame["text"], frame["classes"])

    def close(self):
        super().close()
        while self.stack:
            frame = self.stack.pop()
            if frame.get("event_candidate") and not frame["event_candidate"]["anchor_title"]:
                frame["event_candidate"]["anchor_title"] = frame["text"]
            for candidate in frame["candidates"]:
                self._save(candidate, frame["text"], frame["classes"])

    def _save(self, candidate, text, classes):
        title = candidate["anchor_title"] or _name_from_slug(candidate["slug"])
        title = re.sub(r"\s+", " ", title).strip()
        if not MAIN_EVENT.search(title):
            return
        eid = candidate["event_id"]
        self.events[eid] = {
            "event_id": eid,
            "name": title,
            "tier": _tier(title),
            "region": _region(title),
            "status": _status(text, classes),
            "url": "https://www.vlr.gg/event/%s/%s" % (eid, candidate["slug"]),
        }

def _load_catalog():
    current = {"schema_version": 1, "events": []}
    if CATALOG.exists():
        try:
            current = json.loads(CATALOG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("catalogo.json invalido; arquivo anterior preservado")
    known = {int(e["event_id"]): e for e in current.get("events", [])
             if isinstance(e, dict) and e.get("event_id") is not None}
    if LEGACY_CATALOG.exists():
        legacy = json.loads(LEGACY_CATALOG.read_text(encoding="utf-8"))
        for event in legacy.get("events", []):
            eid = int(event["event_id"])
            if eid not in known:
                known[eid] = {
                    **event, "tier": event.get("tier") or _tier(event.get("name", "")),
                    "status": "historical", "active": False,
                    "first_seen_at": None, "last_seen_at": None,
                    "source": "catalogo_2026.json",
                }
    return current, known

def sync_catalog():
    request = Request(EVENTS_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; VavaComps/1.0)"})
    with urlopen(request, timeout=20) as response:
        html = response.read(4_000_000).decode("utf-8", "replace")
    parser = EventListParser()
    parser.feed(html)
    parser.close()
    if not parser.events:
        raise ValueError("VLR nao retornou eventos principais reconheciveis; catalogo anterior preservado")

    current, known = _load_catalog()
    now = _now()
    added, updated = [], []
    for eid, found in parser.events.items():
        old = known.get(eid, {})
        status = found["status"]
        active = status in ("ongoing", "upcoming")
        known[eid] = {
            **old, **found,
            "active": active if status != "discovered" else bool(old.get("active", False)),
            "first_seen_at": old.get("first_seen_at") or now,
            "last_seen_at": now,
            "source": "vlr.gg/events",
        }
        (updated if old else added).append(eid)

    result = {
        "schema_version": 1,
        "source": EVENTS_URL,
        "last_sync_at": now,
        "events": sorted(known.values(), key=lambda e: (e.get("tier", ""), e.get("name", "").casefold(), int(e["event_id"]))),
    }
    temp = CATALOG.with_suffix(".json.tmp")
    STORE.mkdir(parents=True, exist_ok=True)
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CATALOG)
    return {"eventos_encontrados": len(parser.events), "novos": added,
            "atualizados": updated, "total_catalogados": len(known),
            "ativos_detectados": sum(1 for e in known.values() if e.get("active"))}

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        print(json.dumps(sync_catalog(), ensure_ascii=False))
    else:
        raise SystemExit("Uso: python -m backend.v4_discovery sync")
