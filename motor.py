"""Roda o ciclo diário: recalcula o score de cada planta e decide quem avisar."""
import datetime

import clima
import config
import db
import regras_score

# Até quantos dias à frente olhamos a previsão do tempo pra agendar um
# lembrete proativo ("🌦️ Possível rega") antes da planta realmente cruzar
# o score de 100.
DIAS_JANELA_PROJECAO = 2


def rodar_ciclo(conn, hoje=None):
    hoje = hoje or datetime.date.today()
    coordenadas_por_cidade = {}
    resumo = {
        "novos_avisos": [],
        "ainda_atrasadas": [],
        "atualizadas": [],
        "adiados": [],
        "projecoes": [],
    }

    for planta in db.listar_plantas(conn):
        cidade = planta["cidade"]
        if cidade not in coordenadas_por_cidade:
            coordenadas_por_cidade[cidade] = config.resolver_coordenadas(cidade)
        lat, lon = coordenadas_por_cidade[cidade]

        # dias_futuros = janela de projeção + o dia de hoje, senão a API só
        # devolve o dia atual e não temos como projetar os próximos dias.
        resposta = clima.buscar_dados_climaticos(lat, lon, dias_futuros=DIAS_JANELA_PROJECAO + 1)
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

        if adiar:
            # `novo_score` fica congelado no score anterior quando o aviso é
            # adiado (por isso não teria como aparecer no bloco abaixo) — o
            # que importa aqui é o valor CALCULADO (score_projetado): é ele
            # que diz se a planta cruzaria 100 hoje se não fosse a previsão
            # forte de chuva. Nenhum evento é criado/alterado no Calendar;
            # se a chuva não se confirmar, a planta reaparece em novos_avisos
            # (ou aqui de novo) num ciclo futuro.
            if score_projetado >= 100:
                resumo["adiados"].append({
                    "nome": planta["nome"],
                    "score": score_projetado,
                })
        elif novo_score >= 100:
            if planta["evento_calendario_id"]:
                resumo["ainda_atrasadas"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "evento_calendario_id": planta["evento_calendario_id"],
                })
            else:
                aviso = {
                    "nome": planta["nome"],
                    "score": novo_score,
                    "planta_id": planta["id"],
                }
                if planta.get("evento_projetado_id"):
                    # Já existia um lembrete de "previsão" pra essa planta —
                    # o agente deve confirmá-lo em vez de criar um evento
                    # novo (ver instruções da tarefa agendada).
                    aviso["evento_projetado_id"] = planta["evento_projetado_id"]
                resumo["novos_avisos"].append(aviso)
        else:
            projecao = _projetar_previsao(planta, resposta, hoje, novo_score)
            if projecao is not None:
                resumo["projecoes"].append(projecao)

    return resumo


def _projetar_previsao(planta, resposta_clima, hoje, score_atual):
    """Olha até DIAS_JANELA_PROJECAO dias à frente pra ver se a planta deve
    cruzar o score de rega em breve, com base na previsão do tempo.

    Devolve uma entrada de resumo com "acao" "criar"/"atualizar"/"cancelar"
    pro agente aplicar no Google Calendar, ou None se não há nada a fazer.
    """
    acumulado = score_atual
    data_prevista = None
    dados_insuficientes = False

    for dias_a_frente in range(1, DIAS_JANELA_PROJECAO + 1):
        data_futura = hoje + datetime.timedelta(days=dias_a_frente)
        try:
            clima_futuro = clima.clima_do_dia(resposta_clima, data_futura.isoformat())
        except (ValueError, KeyError):
            # A API não trouxe previsão pra esse dia — não temos base pra
            # decidir com confiança, então não mexemos em nenhum evento já
            # existente (evita cancelar uma previsão válida por engano).
            dados_insuficientes = True
            break

        incremento_base_f = regras_score.calcular_incremento_base(planta, data_futura)
        incremento_clima_f = clima.calcular_incremento_clima(planta, clima_futuro)
        acumulado += incremento_base_f + incremento_clima_f

        if acumulado >= 100:
            data_prevista = data_futura.isoformat()
            break

    if dados_insuficientes:
        return None

    evento_projetado_id = planta.get("evento_projetado_id")

    if data_prevista:
        entrada = {
            "nome": planta["nome"],
            "planta_id": planta["id"],
            "acao": "atualizar" if evento_projetado_id else "criar",
            "data_prevista": data_prevista,
        }
        if evento_projetado_id:
            entrada["evento_projetado_id"] = evento_projetado_id
        return entrada

    if evento_projetado_id:
        # Antes projetávamos que ia cruzar 100 na janela, mas com a
        # previsão de hoje isso não se sustenta mais (ex: choveu ou a
        # previsão de chuva mudou) — cancela o lembrete de previsão.
        return {
            "nome": planta["nome"],
            "planta_id": planta["id"],
            "acao": "cancelar",
            "evento_projetado_id": evento_projetado_id,
        }

    return None
