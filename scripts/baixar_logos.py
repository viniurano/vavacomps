"""Baixa as logos oficiais dos times do JSON para img/teams/<team_id>.png.
Execute em Vacomp: python scripts/baixar_logos.py
Requer: python -m pip install vlrdevapi requests pillow
"""
import io
import json
from pathlib import Path
from urllib.parse import urljoin
import requests
from PIL import Image
from vlrdevapi import VLRClient

ROOT = Path(__file__).resolve().parent.parent
DBS = [ROOT / "dados" / "vct_comps_geral.json", ROOT / "dados" / "gc_championship_2026.json"]
OUT = ROOT / "img" / "teams"
OUT.mkdir(parents=True, exist_ok=True)
teams = {}
for db in DBS:
    if db.exists():
        for team in json.loads(db.read_text(encoding="utf-8"))["equipes"].values():
            teams[str(team["team_id"])] = team
with VLRClient() as client, requests.Session() as session:
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; VavaComps/1.0)"})
    for team in teams.values():
        team_id = team["team_id"]
        target = OUT / f"{team_id}.png"
        if target.exists():
            print(f"OK (ja existe): {team['nome']}")
            continue
        try:
            info = client.team(team_id).info()
            logo_url = getattr(info, "logo_url", None)
            if not logo_url:
                # Alguns modelos da API expoem a logo nas series, nao no perfil.
                series_id = team["mapas"][0]["serie_id"]
                series = client.series(series_id).info()
                match_team = next((t for t in (series.team1, series.team2) if str(t.id) == str(team_id)), None)
                logo_url = getattr(match_team, "logo_url", None)
            if not logo_url:
                raise ValueError("A API nao retornou logo_url")
            url = urljoin("https://www.vlr.gg/", str(logo_url))
            if not url.startswith("https://"):
                raise ValueError("URL de logo invalida")
            response = session.get(url, timeout=20)
            response.raise_for_status()
            if len(response.content) > 8_000_000:
                raise ValueError("Imagem muito grande")
            with Image.open(io.BytesIO(response.content)) as image:
                image.thumbnail((512, 512))
                image.convert("RGBA").save(target, "PNG")
            print(f"OK: {team['nome']} -> {target.relative_to(ROOT)}")
        except Exception as exc:
            print(f"FALHOU: {team['nome']} ({team_id}) -> {type(exc).__name__}: {exc}")
print("Concluido. Confira img/teams/ e recarregue o navegador com Ctrl+F5.")
