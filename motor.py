"""Roda o ciclo diário: recalcula o score de cada planta e decide quem avisar."""
import datetime

import clima
import config
import db
import regras_score


LIMIAR_DELTA_CORRECAO = 0.01


def corrigir_historico_retroativo(conn, planta, resposta_clima, hoje_iso):
    """Corrige dias passados cujo registro em historico_scores foi gravado
    com uma estimativa de clima ainda provisória. O motivo: quando o ciclo
    roda no dia D, a API devolve o clima de D como previsão/nowcast (o dia
    ainda não terminou) — só fica reconciliado com a medição real depois,
    quando D aparece como "passado" numa chamada futura. Sem essa correção,
    um dia de chuva forte que só "aparece" na medição tarde fica
    subestimado pra sempre no score, mesmo a planta tendo sido efetivamente
    regada pela chuva (é exatamente o caso de uma planta exposta que devia
    ter o aviso de rega cancelado depois de chover bastante).

    Para cada data anterior a hoje presente na resposta do clima que já
    tem registro em historico_scores, recalcula o incremento_clima com o
    dado agora reconciliado, atualiza esse registro do histórico e acumula
    a diferença. Retorna (delta_total, lista_de_correcoes) — delta_total
    deve ser somado ao score atual da planta pelo chamador (o histórico já
    fica corrigido aqui dentro, mas o campo `score` da planta é
    responsabilidade de quem chamou)."""
    cur = conn.cursor()
    delta_total = 0.0
    correcoes = []
    for data_iso in resposta_clima["daily"]["time"]:
        if data_iso >= hoje_iso:
            continue
        cur.execute(
            "SELECT incremento_base, incremento_clima, score_final, precipitacao_mm "
            "FROM historico_scores WHERE planta_id = ? AND data = ?",
            (planta["id"], data_iso),
        )
        linha = cur.fetchone()
        if linha is None:
            continue
        incremento_base, incremento_clima_antigo, score_final_antigo, precip_antiga = linha

        clima_dia = clima.clima_do_dia(resposta_clima, data_iso)
        incremento_clima_novo = clima.calcular_incremento_clima(planta, clima_dia)
        delta = incremento_clima_novo - incremento_clima_antigo
        if abs(delta) < LIMIAR_DELTA_CORRECAO:
            continue

        score_final_novo = score_final_antigo + delta
        db.registrar_historico_score(
            conn, planta["id"], data_iso,
            incremento_base, incremento_clima_novo, score_final_novo,
            clima_dia["et0"], clima_dia["precipitacao_mm"],
        )
        delta_total += delta
        correcoes.append({
            "data": data_iso,
            "precipitacao_mm_antiga": precip_antiga,
            "precipitacao_mm_nova": clima_dia["precipitacao_mm"],
            "delta_score": round(delta, 2),
        })
    return delta_total, correcoes


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
        "adiados": [], "projecoes": [], "correcoes_retroativas": [],
    }

    for planta in db.listar_plantas(conn):
        cidade = planta["cidade"]
        if cidade not in coordenadas_por_cidade:
            coordenadas_por_cidade[cidade] = config.resolver_coordenadas(cidade)
        lat, lon = coordenadas_por_cidade[cidade]

        if cidade not in clima_por_cidade:
            clima_por_cidade[cidade] = clima.buscar_dados_climaticos(lat, lon)
        resposta = clima_por_cidade[cidade]

        # Correção retroativa roda ANTES do ja_processado_hoje: ela mexe
        # com dias passados, então tem que acontecer mesmo numa segunda
        # chamada do ciclo no mesmo dia (senão uma correção que só existe
        # na resposta de hoje nunca seria aplicada, já que amanhã esse dia
        # já não estará mais na janela de past_days).
        delta_correcao, dias_corrigidos = corrigir_historico_retroativo(
            conn, planta, resposta, hoje_iso
        )
        if dias_corrigidos:
            score_antes_correcao = planta["score"]
            planta["score"] = max(0.0, planta["score"] + delta_correcao)
            db.atualizar_score(conn, planta["id"], planta["score"])
            entrada_correcao = {
                "nome": planta["nome"],
                "planta_id": planta["id"],
                "score_antes": round(score_antes_correcao, 2),
                "score_depois": round(planta["score"], 2),
                "dias_corrigidos": dias_corrigidos,
            }
            if planta["score"] < 100 and planta["evento_calendario_id"]:
                # a correção mostrou que a planta já tinha sido regada pela
                # chuva de fato — o lembrete confirmado que existe hoje
                # ficou obsoleto. Reporta pro agente cancelar no Calendar; e,
                # pro RESTO deste ciclo, trata como se não houvesse mais
                # evento (senão ela reapareceria em ainda_atrasadas logo
                # abaixo, contradizendo o cancelamento reportado aqui).
                entrada_correcao["evento_calendario_id_a_cancelar"] = planta["evento_calendario_id"]
                planta = {**planta, "evento_calendario_id": None}
            resumo["correcoes_retroativas"].append(entrada_correcao)

        if db.ja_processado_hoje(conn, planta["id"], hoje_iso):
            # já rodou hoje pra essa planta: não soma o incremento de novo.
            # Um lembrete que JÁ existe (evento_calendario_id setado)
            # continua aparecendo em ainda_atrasadas numa segunda chamada.
            # Mas se ainda não existe evento, não dá pra saber aqui se a
            # planta cruzou 100 "limpo" ou se foi adiada na primeira
            # passada de hoje (depende do clima do momento, que não fica
            # guardado) — então não reclassificamos como novo aviso numa
            # segunda chamada: reexpor arriscaria criar um lembrete
            # duplicado ou desfazer silenciosamente um adiamento já
            # decidido hoje. O ciclo de amanhã reavalia isso do zero.
            if planta["score"] >= 100 and planta["evento_calendario_id"]:
                resumo["ainda_atrasadas"].append({
                    "nome": planta["nome"],
                    "score": planta["score"],
                    "evento_calendario_id": planta["evento_calendario_id"],
                })
            continue

        clima_hoje = clima.clima_do_dia(resposta, hoje_iso)

        incremento_base = regras_score.calcular_incremento_base(planta, hoje)
        incremento_clima = clima.calcular_incremento_clima(planta, clima_hoje)
        score_projetado = planta["score"] + incremento_base + incremento_clima

        adiar = clima.deve_adiar_aviso(score_projetado, clima_hoje)
        # O score sempre avança pro valor calculado, com piso em 0 (chuva
        # forte não pode gerar score negativo). "adiar" só controla se a
        # planta aparece em novos_avisos hoje — não congela o score, senão
        # ela ficaria travada pra sempre caso a chuva prevista não se
        # confirme.
        novo_score = max(0.0, score_projetado)

        # O histórico sempre registra o valor CALCULADO (score_projetado,
        # sem piso), pra manter o registro fiel ao que foi de fato apurado
        # naquele dia, mesmo que o score aplicado à planta tenha piso em 0.
        db.registrar_historico_score(
            conn, planta["id"], hoje_iso,
            incremento_base, incremento_clima, score_projetado,
            clima_hoje["et0"], clima_hoje["precipitacao_mm"],
        )
        db.atualizar_score(conn, planta["id"], novo_score)
        resumo["atualizadas"].append({"nome": planta["nome"], "score": novo_score})

        if novo_score >= 100:
            if planta["evento_calendario_id"]:
                # já existe lembrete pra essa planta: um adiamento decidido
                # agora, sobre a crossing de HOJE, não desfaz um evento que
                # já estava confirmado de antes.
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
        elif not planta["evento_calendario_id"]:
            # Só simula projeção pra quem ainda não tem lembrete confirmado.
            # Uma planta que já tem evento_calendario_id pode cair de volta
            # abaixo de 100 (chuva medida hoje) sem que isso vire uma nova
            # projeção: os dois campos (evento_calendario_id e
            # evento_projetado_id) nunca podem ficar preenchidos ao mesmo
            # tempo pra mesma planta (ver ledger, achado 1 da revisão
            # final). O evento confirmado continua valendo até `regar()`
            # limpar ele.
            #
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
