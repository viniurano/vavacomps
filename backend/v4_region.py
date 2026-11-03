"""Coleta regional incremental para preencher os JSONs V4.
Uso: python -m backend.v4_region americas [limite_por_evento]
"""
import json
import sys
import time
from datetime import datetime, timezone

from backend.main import REGIONAL_EVENTS, event_index
from backend import v4_store


def collect_region(region, limit=30):
    region = region.lower()
    if region not in REGIONAL_EVENTS:
        raise SystemExit("Regiao invalida: " + region)
    report = {"regiao": region, "eventos": [], "limite_por_evento": limit}
    for event_id, label in REGIONAL_EVENTS[region]:
        index = event_index(event_id)
        data = v4_store.event_data(event_id)
        done = {str(k) for k in data.get("series", {})}
        pending = [m for m in index["partidas"] if str(m["id"]) not in done]
        batch = pending[:limit]
        results = []
        for match in batch:
            try:
                result = v4_store.collect_series(
                    event_id, match["id"], force=True, match_date=match.get("data")
                )
                results.append(result)
            except Exception as exc:
                results.append({"serie_id": match["id"], "status": "erro", "erro": str(exc)[:180]})
                if "429" in str(exc):
                    break
            time.sleep(2)
        latest = v4_store.event_data(event_id)
        report["eventos"].append({
            "event_id": event_id,
            "nome": label,
            "series_concluidas_no_vlr": len(index["partidas"]),
            "ja_salvas_antes": len(done),
            "tentadas_agora": len(batch),
            "series_salvas_ao_final": len(latest.get("series", {})),
            "pendentes": max(0, len(index["partidas"]) - len(latest.get("series", {}))),
            "resultados": results,
        })
        if any("429" in str(x) for x in results):
            break
    report["executado_em"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    collect_region(sys.argv[1] if len(sys.argv) > 1 else "", int(sys.argv[2]) if len(sys.argv) > 2 else 30)
