
import json
from pathlib import Path
from vlrdevapi import VLRClient

EVENT_ID = 2766
CAMPEONATO = "Valorant Champions 2026"

saida = Path("dados/vct_comps_geral.json")
saida.parent.mkdir(parents=True, exist_ok=True)

resultado = {
    "campeonato": CAMPEONATO,
    "event_id": EVENT_ID,
    "equipes": {}
}

def salvar_equipe(dados_equipe, adversario, jogo, info, data, lado):
    equipe_id = dados_equipe.team_id
    nome = dados_equipe.team_name

    jogadores = [
        {
            "nome": p.name,
            "id": p.player_id,
            "agente": p.agents[0],
            "stats": p.stats.model_dump(mode="json")
        }
        for p in dados_equipe.players
        if p.agents
    ]

    if len(jogadores) != 5:
        print(f"  Composição incompleta: {nome} em {jogo.map_name}")
        return

    primeiro = lado == 1

    pontos = jogo.team1_score if primeiro else jogo.team2_score
    pontos_adv = jogo.team2_score if primeiro else jogo.team1_score

    ataque = jogo.team1_attack_rounds if primeiro else jogo.team2_attack_rounds
    defesa = jogo.team1_defense_rounds if primeiro else jogo.team2_defense_rounds

    chave = str(equipe_id)

    if chave not in resultado["equipes"]:
        resultado["equipes"][chave] = {
            "team_id": equipe_id,
            "nome": nome,
            "mapas": []
        }

    resultado["equipes"][chave]["mapas"].append({
        "serie_id": info.series_id,
        "game_id": jogo.game_id,
        "mapa": jogo.map_name,
        "adversario": adversario.team_name,
        "adversario_id": adversario.team_id,
        "data": data,
        "placar": [pontos, pontos_adv],
        "vitoria": pontos > pontos_adv,
        "rounds_ataque": ataque,
        "rounds_defesa": defesa,
        "jogadores": jogadores,
        "composicao": sorted(p["agente"] for p in jogadores)
    })


with VLRClient() as client:
    partidas = client.event(EVENT_ID).matches().matches

    print(f"Partidas encontradas: {len(partidas)}")

    for partida in partidas:
        # Ignora séries não concluídas.
        if partida.status.value != "completed":
            continue

        print(f"Processando série {partida.match_id}...")

        try:
            serie = client.series(partida.match_id)
            info = serie.info()
            dados = serie.players()

            for jogo in info.games:
                if not jogo.played:
                    continue

                mapa = next(
                    (
                        m for m in dados.maps
                        if str(m.game_id) == str(jogo.game_id)
                    ),
                    None
                )

                if mapa is None:
                    print(f"  Sem dados: {jogo.map_name}")
                    continue

                data = partida.match_date.isoformat()

                salvar_equipe(
                    mapa.team1, mapa.team2,
                    jogo, info, data, 1
                )

                salvar_equipe(
                    mapa.team2, mapa.team1,
                    jogo, info, data, 2
                )

        except Exception as erro:
            print(
                f"  Erro na série {partida.match_id}: "
                f"{type(erro).__name__}: {erro}"
            )

saida.write_text(
    json.dumps(resultado, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

total_equipes = len(resultado["equipes"])
total_registros = sum(
    len(e["mapas"])
    for e in resultado["equipes"].values()
)

print("\n=== RESULTADO ===")
print(f"Equipes: {total_equipes}")
print(f"Registros de mapas: {total_registros}")
print(f"Arquivo: {saida}")
