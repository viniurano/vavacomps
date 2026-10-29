
from vlrdevapi import VLRClient

MATCH_ID = 753450

print("Buscando jogadores e agentes de LOUD x EDG...")

try:
    with VLRClient() as client:
        serie = client.series(MATCH_ID)

        jogadores = serie.players()

        print("\n=== JOGADORES E AGENTES ===")
        print(jogadores.model_dump_json(indent=2))

except Exception as erro:
    print("Erro:", type(erro).__name__, str(erro))
