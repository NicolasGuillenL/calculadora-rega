"""Roda o ciclo diário: recalcula o score de cada planta e decide quem avisar."""
import datetime

import clima
import config
import db
import regras_score


def rodar_ciclo(conn, hoje=None):
    hoje = hoje or datetime.date.today()
    coordenadas_por_cidade = {}
    resumo = {"novos_avisos": [], "ainda_atrasadas": [], "atualizadas": []}

    for planta in db.listar_plantas(conn):
        cidade = planta["cidade"]
        if cidade not in coordenadas_por_cidade:
            coordenadas_por_cidade[cidade] = config.resolver_coordenadas(cidade)
        lat, lon = coordenadas_por_cidade[cidade]

        resposta = clima.buscar_dados_climaticos(lat, lon)
        clima_hoje = clima.clima_do_dia(resposta, hoje.isoformat())

        incremento_base = regras_score.calcular_incremento_base(planta, hoje)
        incremento_clima = clima.calcular_incremento_clima(planta, clima_hoje)
        score_projetado = planta["score"] + incremento_base + incremento_clima

        adiar = clima.deve_adiar_aviso(score_projetado, clima_hoje)
        novo_score = planta["score"] if adiar else score_projetado

        # O histórico sempre registra o valor CALCULADO (score_projetado),
        # independentemente de o aviso ter sido adiado. O que muda com o
        # adiamento é apenas o score efetivamente aplicado à planta
        # (novo_score), não o que foi registrado no histórico.
        db.registrar_historico_score(
            conn, planta["id"], hoje.isoformat(),
            incremento_base, incremento_clima, score_projetado,
            clima_hoje["et0"], clima_hoje["precipitacao_mm"],
        )
        db.atualizar_score(conn, planta["id"], novo_score)
        resumo["atualizadas"].append({"nome": planta["nome"], "score": novo_score})

        if novo_score >= 100:
            if planta["evento_calendario_id"]:
                resumo["ainda_atrasadas"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "evento_calendario_id": planta["evento_calendario_id"],
                })
            else:
                resumo["novos_avisos"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "planta_id": planta["id"],
                })

    return resumo
