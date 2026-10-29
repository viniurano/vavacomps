
import json
from pathlib import Path
from vlrdevapi import VLRClient

EVENT_ID = 2766
TEAM_ID = 6961

saida = Path("dados/vct_comps.json")
saida.parent.mkdir(parents=True, exist_ok=True)

resultado = {
    "campeonato": "Valorant Champions 2026",
    "event_id": EVENT_ID,
    "equipes": {}
}

with VLRClient() as client:
    evento = client.event(EVENT_ID)
    partidas = evento.matches().matches

    partidas_loud = [
        partida for partida in partidas
        if any(equipe.id == TEAM_ID for equipe in partida.teams)
        and partida.status.value == "completed"
    ]

    print(f"Encontradas {len(partidas_loud)} séries da LOUD.")

    mapas = []

    for partida in partidas_loud:
        print(f"Processando série {partida.match_id}...")

        serie = client.series(partida.match_id)
        info = serie.info()
        jogadores = serie.players()

        for jogo in info.games:
            if not jogo.played:
                continue

            dados_mapa = next(
                (
                    mapa for mapa in jogadores.maps
                    if str(mapa.game_id) == str(jogo.game_id)
                ),
                None
            )

            if dados_mapa is None:
                print(f"  Aviso: sem jogadores para {jogo.map_name}")
                continue

            equipe = (
                dados_mapa.team1
                if dados_mapa.team1.team_id == TEAM_ID
                else dados_mapa.team2
            )

            adversario = (
                dados_mapa.team2
                if dados_mapa.team1.team_id == TEAM_ID
                else dados_mapa.team1
            )

            loud_primeira = info.team1.id == TEAM_ID

            pontos = (
                jogo.team1_score if loud_primeira
                else jogo.team2_score
            )
            pontos_adversario = (
                jogo.team2_score if loud_primeira
                else jogo.team1_score
            )

            ataque = (
                jogo.team1_attack_rounds if loud_primeira
                else jogo.team2_attack_rounds
            )
            defesa = (
                jogo.team1_defense_rounds if loud_primeira
                else jogo.team2_defense_rounds
            )

            jogadores_loud = [
                {
                    "nome": jogador.name,
                    "id": jogador.player_id,
                    "agente": jogador.agents[0],
                    "stats": jogador.stats.model_dump(mode="json")
                }
                for jogador in equipe.players
                if jogador.agents
            ]

            if len(jogadores_loud) != 5:
                print(f"  Aviso: composição incompleta em {jogo.map_name}")
                continue

            mapas.append({
                "serie_id": partida.match_id,
                "game_id": jogo.game_id,
                "mapa": jogo.map_name,
                "adversario": adversario.team_name,
                "data": partida.match_date.isoformat(),
                "placar": [pontos, pontos_adversario],
                "vitoria": pontos > pontos_adversario,
                "rounds_ataque": ataque,
                "rounds_defesa": defesa,
                "jogadores": jogadores_loud,
                "composicao": sorted(
                    jogador["agente"] for jogador in jogadores_loud
                )
            })

    resultado["equipes"]["LOUD"] = {
        "team_id": TEAM_ID,
        "mapas": mapas
    }

saida.write_text(
    json.dumps(resultado, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"\nJSON salvo em: {saida}")
print(f"Total de mapas coletados: {len(mapas)}")
