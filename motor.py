"""Roda o ciclo diário: recalcula o score de cada planta e decide quem avisar."""
import datetime

import clima
import config
import db
import regras_score


def simular_projecao(planta, resposta_clima, hoje):
    """Simula o score da planta pros dias futuros disponíveis na resposta do
    Open-Meteo, sem gravar nada em lugar nenhum — usa a mesma fórmula do
    ciclo real, incluindo a chuva PREVISTA (não medida) pros dias que ainda
    não aconteceram. Retorna a data ISO em que o score projetado cruzaria
    100, ou None se não cruza dentro dos dias disponíveis na resposta."""
    hoje_iso = hoje.isoformat()
    datas_futuras = sorted(d for d in resposta_clima["daily"]["time"] if d > hoje_iso)

    score = planta["score"]
    for data_iso in datas_futuras:
        data = datetime.date.fromisoformat(data_iso)
        clima_dia = clima.clima_do_dia(resposta_clima, data_iso)
        incremento_base = regras_score.calcular_incremento_base(planta, data)
        incremento_clima = clima.calcular_incremento_clima(planta, clima_dia)
        score = max(0.0, score + incremento_base + incremento_clima)
        if score >= 100:
            return data_iso
    return None


def rodar_ciclo(conn, hoje=None):
    hoje = hoje or datetime.date.today()
    hoje_iso = hoje.isoformat()
    coordenadas_por_cidade = {}
    clima_por_cidade = {}
    resumo = {
        "novos_avisos": [], "ainda_atrasadas": [], "atualizadas": [],
        "adiados": [], "projecoes": [],
    }

    for planta in db.listar_plantas(conn):
        if db.ja_processado_hoje(conn, planta["id"], hoje_iso):
            if planta["score"] >= 100 and planta["evento_calendario_id"]:
                resumo["ainda_atrasadas"].append({
                    "nome": planta["nome"],
                    "score": planta["score"],
                    "evento_calendario_id": planta["evento_calendario_id"],
                })
            continue

        cidade = planta["cidade"]
        if cidade not in coordenadas_por_cidade:
            coordenadas_por_cidade[cidade] = config.resolver_coordenadas(cidade)
        lat, lon = coordenadas_por_cidade[cidade]

        if cidade not in clima_por_cidade:
            clima_por_cidade[cidade] = clima.buscar_dados_climaticos(lat, lon)
        resposta = clima_por_cidade[cidade]
        clima_hoje = clima.clima_do_dia(resposta, hoje_iso)

        incremento_base = regras_score.calcular_incremento_base(planta, hoje)
        incremento_clima = clima.calcular_incremento_clima(planta, clima_hoje)
        score_projetado = planta["score"] + incremento_base + incremento_clima

        adiar = clima.deve_adiar_aviso(score_projetado, clima_hoje)
        novo_score = max(0.0, score_projetado)

        db.registrar_historico_score(
            conn, planta["id"], hoje_iso,
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
            elif adiar:
                resumo["adiados"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "planta_id": planta["id"],
                })
            else:
                entrada = {"nome": planta["nome"], "score": novo_score, "planta_id": planta["id"]}
                if planta["evento_projetado_id"]:
                    entrada["evento_projetado_id"] = planta["evento_projetado_id"]
                resumo["novos_avisos"].append(entrada)
        else:
            # não cruzou hoje: verifica se cruzaria dentro da janela de
            # projeção (2 dias), pra manter o evento "previsão" em dia. A
            # simulação parte do score JÁ ATUALIZADO de hoje (novo_score),
            # não do score antigo em `planta` (que é o valor de antes do
            # ciclo rodar) — senão a projeção subestima quanto a planta já
            # avançou hoje.
            planta_com_score_atual = {**planta, "score": novo_score}
            data_prevista = simular_projecao(planta_com_score_atual, resposta, hoje)
            projetado_atual = planta["evento_projetado_id"]
            if data_prevista:
                acao = {
                    "nome": planta["nome"],
                    "planta_id": planta["id"],
                    "data_prevista": data_prevista,
                    "acao": "atualizar" if projetado_atual else "criar",
                }
                if projetado_atual:
                    acao["evento_projetado_id"] = projetado_atual
                resumo["projecoes"].append(acao)
            elif projetado_atual:
                resumo["projecoes"].append({
                    "acao": "cancelar",
                    "nome": planta["nome"],
                    "planta_id": planta["id"],
                    "evento_projetado_id": projetado_atual,
                })

    return resumo
