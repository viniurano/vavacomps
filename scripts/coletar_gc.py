"""Game Changers Championship 2026: coleta partidas finalizadas. Execute: python scripts/coletar_gc.py"""
import json
from pathlib import Path
from vlrdevapi import VLRClient
OUT=Path(__file__).resolve().parent.parent/'dados'/'gc_championship_2026.json'
EVENT_ID=3134
result={'campeonato':'Game Changers 2026: Championship São Paulo','event_id':EVENT_ID,'equipes':{}}
def add(team,other,game,info,date):
    tid=team.team_id
    if str(tid)==str(info.team1.id): side=1
    elif str(tid)==str(info.team2.id): side=2
    else:
        print('  Equipe não identificada:',team.team_name,tid)
        return
    players=[{'nome':p.name,'id':p.player_id,'agente':p.agents[0],'stats':p.stats.model_dump(mode='json')} for p in team.players if p.agents]
    if len(players)!=5:
        print('  Composição incompleta:',team.team_name,game.map_name)
        return
    score=game.team1_score if side==1 else game.team2_score
    oppscore=game.team2_score if side==1 else game.team1_score
    if score is None or oppscore is None:return
    entry=result['equipes'].setdefault(str(tid),{'team_id':tid,'nome':team.team_name,'mapas':[]})
    entry['mapas'].append({'serie_id':info.series_id,'game_id':game.game_id,'mapa':game.map_name,'adversario':other.team_name,'adversario_id':other.team_id,'data':date,'placar':[score,oppscore],'vitoria':score>oppscore,'rounds_ataque':game.team1_attack_rounds if side==1 else game.team2_attack_rounds,'rounds_defesa':game.team1_defense_rounds if side==1 else game.team2_defense_rounds,'jogadores':players,'composicao':sorted(p['agente'] for p in players)})
with VLRClient() as client:
    matches=client.event(EVENT_ID).matches().matches
    print('Séries encontradas:',len(matches))
    for match in matches:
        if match.status.value!='completed':continue
        print('Processando série',match.match_id)
        try:
            series=client.series(match.match_id)
            info=series.info()
            data=series.players()
            for game in info.games:
                if not game.played:continue
                m=next((x for x in data.maps if str(x.game_id)==str(game.game_id)),None)
                if m is None:
                    print('  Sem estatísticas:',game.map_name)
                    continue
                date=match.match_date.isoformat()
                add(m.team1,m.team2,game,info,date)
                add(m.team2,m.team1,game,info,date)
        except Exception as err:print('  Erro:',type(err).__name__,err)
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
n=sum(len(t['mapas']) for t in result['equipes'].values())
print('Equipes:',len(result['equipes']),'Mapas:',n//2,'Registros:',n,'Arquivo:',OUT)
