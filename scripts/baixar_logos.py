"""Baixa logos de todas as equipes conhecidas nos snapshots e JSONs V4.
Salva em img/teams/<team_id>.png para uso direto pelo frontend.
"""
import io
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from PIL import Image
from vlrdevapi import VLRClient

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "img" / "teams"
OUT.mkdir(parents=True, exist_ok=True)
SOURCES = [
    ROOT / "dados" / "vct_comps.json",
    ROOT / "dados" / "vct_comps_geral.json",
    ROOT / "dados" / "gc_championship_2026.json",
]
SOURCES.extend(sorted((ROOT / "dados" / "v4" / "eventos").glob("*.json")))
teams = {}

for path in SOURCES:
    if not path.is_file():
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"IGNORADO {path.name}: {exc}")
        continue
    for key, team in (data.get("equipes") or {}).items():
        if not isinstance(team, dict) or not team.get("team_id"):
            continue
        tid = str(team["team_id"])
        entry = teams.setdefault(tid, {"team_id": int(tid), "nome": team.get("nome") or str(key)})
        if not entry.get("nome") and team.get("nome"):
            entry["nome"] = team["nome"]

def profile_logo(session, team_id):
    response = session.get(f"https://www.vlr.gg/team/{team_id}/", timeout=15)
    response.raise_for_status()
    html = response.text
    patterns = [
        r"""team-header-logo[\s\S]{0,1200}?<img[^>]+(?:src|data-src)=["']([^"']+)""",
        r"""<img[^>]+class=["'][^"']*team-logo[^"']*["'][^>]+src=["']([^"']+)""",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return urljoin("https://www.vlr.gg/", match.group(1))
    return None

ok = failed = skipped = 0
with VLRClient() as client, requests.Session() as session:
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; VavaComps/1.0)"})
    for tid, team in sorted(teams.items(), key=lambda item: item[1]["nome"].lower()):
        target = OUT / f"{tid}.png"
        if target.is_file() and target.stat().st_size > 100:
            skipped += 1
            continue
        logo_url = None
        try:
            try:
                info = client.team(int(tid)).info()
                logo_url = getattr(info, "logo_url", None)
            except Exception as exc:
                print(f"API perfil {team['nome']} ({tid}): {type(exc).__name__}")
            if not logo_url:
                logo_url = profile_logo(session, tid)
            if not logo_url:
                raise ValueError("logo nao encontrada no perfil VLR")
            logo_url = urljoin("https://www.vlr.gg/", str(logo_url))
            if not logo_url.startswith("https://"):
                raise ValueError("URL de logo invalida")
            response = session.get(logo_url, timeout=20)
            response.raise_for_status()
            if not response.content or len(response.content) > 8_000_000:
                raise ValueError("tamanho de imagem invalido")
            with Image.open(io.BytesIO(response.content)) as image:
                image.thumbnail((512, 512))
                image.convert("RGBA").save(target, "PNG")
            ok += 1
            print(f"OK {team['nome']} ({tid})")
        except Exception as exc:
            failed += 1
            print(f"FALHOU {team['nome']} ({tid}): {type(exc).__name__}: {exc}")

print(json.dumps({"equipes_encontradas": len(teams), "logos_baixadas": ok,
                  "ja_existentes": skipped, "falhas": failed}, ensure_ascii=False))
