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
    resumo = {"novos_avisos": [], "ainda_atrasadas": [], "atualizadas": [], "adiados": []}

    for planta in db.listar_plantas(conn):
        if db.ja_processado_hoje(conn, planta["id"], hoje_iso):
            # já rodou hoje pra essa planta: não soma o incremento de novo.
            # Um lembrete que JÁ existe (evento_calendario_id setado) não
            # pode ficar escondido numa segunda chamada do ciclo no mesmo
            # dia — continua aparecendo em ainda_atrasadas. Mas se ainda não
            # existe evento, não dá pra saber aqui se a planta cruzou 100
            # "limpo" ou se foi adiada na primeira passada de hoje (essa
            # decisão dependeu do clima do momento, que não fica guardado) —
            # então não reclassificamos como novo aviso numa segunda
            # chamada: reexpor arriscaria criar um lembrete duplicado ou
            # ignorar um adiamento que já tinha sido decidido hoje. O ciclo
            # de amanhã reavalia isso do zero.
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
        # O score sempre avança pro valor calculado, com piso em 0 (chuva
        # forte não pode gerar score negativo). "adiar" só controla se a
        # planta aparece em novos_avisos hoje — não congela o score, senão
        # ela fica travada pra sempre caso a chuva prevista não se
        # confirme.
        novo_score = max(0.0, score_projetado)

        # O histórico sempre registra o valor CALCULADO (score_projetado,
        # sem piso), pra manter o registro fiel ao que foi de fato apurado
        # naquele dia.
        db.registrar_historico_score(
            conn, planta["id"], hoje_iso,
            incremento_base, incremento_clima, score_projetado,
            clima_hoje["et0"], clima_hoje["precipitacao_mm"],
        )
        db.atualizar_score(conn, planta["id"], novo_score)
        resumo["atualizadas"].append({"nome": planta["nome"], "score": novo_score})

        if novo_score >= 100:
            if planta["evento_calendario_id"]:
                # já existe lembrete pra essa planta: adiar não desfaz isso.
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
                resumo["novos_avisos"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "planta_id": planta["id"],
                })

    return resumo
