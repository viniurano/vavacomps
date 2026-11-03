"""Atualiza manualmente os mapas de uma equipe em um campeonato VLR."""
import json
import sys


def main(event_id, team_id):
    event_id, team_id = int(event_id), int(team_id)
    if not (1 <= event_id <= 9999999 and team_id > 0):
        raise ValueError("IDs de campeonato/equipe invalidos")

    from backend.main import event_index
    from backend.v4_store import refresh_team

    def discover(eid, tid):
        index = event_index(eid)
        return [
            match for match in index["partidas"]
            if any(int(team["team_id"]) == tid for team in match["equipes"])
        ]

    result = refresh_team(event_id, team_id, discover)
    print(json.dumps({
        "event_id": event_id,
        "team_id": team_id,
        **result,
    }, ensure_ascii=False))
    if result.get("status") == "concluido" and not result.get("series"):
        raise RuntimeError("Nenhuma partida concluida encontrada para esta equipe")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Uso: python -m backend.v4_manual EVENT_ID TEAM_ID")
    main(sys.argv[1], sys.argv[2])
