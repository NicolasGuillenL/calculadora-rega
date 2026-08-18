import datetime
import sqlite3
from unittest.mock import patch

import db
import motor

PLANTA_EXEMPLO = {
    "nome": "Jiboia",
    "temperatura_ideal_c": 24.0,
    "umidade_ideal_pct": 60.0,
    "florescimento": None,
    "crescimento": None,
    "crescimento2": None,
    "poda": None,
    "replantio": None,
    "mudas": None,
    "epoca_mudas": None,
    "exposicao": 5,
    "retencao_substrato": "media",
    "cidade": "Sao Paulo, SP",
}

CLIMA_NEUTRO = {
    "et0": 2.0, "precipitacao_mm": 0.0, "probabilidade_chuva_pct": 10,
    "windspeed_10m_max": 5.0, "uv_index_max": 3.0,
    "umidade_relativa_pct": 55.0, "nebulosidade_pct": 30.0,
}


def _conexao_teste():
    conn = sqlite3.connect(":memory:")
    db.criar_schema(conn)
    return conn


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_atualiza_score_e_grava_historico(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    db.inserir_planta(conn, PLANTA_EXEMPLO)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["score"] > 0
    assert resumo["atualizadas"][0]["nome"] == "Jiboia"

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM historico_scores")
    assert cur.fetchall()[0][0] == 1


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_gera_novo_aviso_quando_cruza_100(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["novos_avisos"]) == 1
    assert resumo["novos_avisos"][0]["nome"] == "Jiboia"
    assert resumo["ainda_atrasadas"] == []


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_nao_duplica_aviso_se_ja_tem_evento(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 120)
    db.marcar_evento_calendario(conn, planta_id, "evento-existente")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo["novos_avisos"] == []
    assert len(resumo["ainda_atrasadas"]) == 1
    assert resumo["ainda_atrasadas"][0]["evento_calendario_id"] == "evento-existente"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
@patch("motor.clima.deve_adiar_aviso", return_value=True)
def test_rodar_ciclo_adiado_avanca_score_e_grava_historico_calculado(
    mock_adiar, mock_clima_dia, mock_busca, mock_coords
):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 50)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    # o score deve avançar normalmente mesmo com o aviso adiado — "adiar"
    # só afeta se a planta aparece em novos_avisos hoje, não o cálculo do
    # score em si (senão a planta fica travada pra sempre se não chover).
    assert planta["score"] > 50
    assert resumo["atualizadas"][0]["score"] == planta["score"]

    cur = conn.cursor()
    cur.execute(
        "SELECT score_final FROM historico_scores WHERE planta_id = ?",
        (planta_id,),
    )
    score_final_historico = cur.fetchall()[0][0]
    assert score_final_historico == planta["score"]


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
@patch("motor.clima.deve_adiar_aviso", return_value=True)
def test_rodar_ciclo_adiado_suprime_novo_aviso_mas_lista_em_adiados(
    mock_adiar, mock_clima_dia, mock_busca, mock_coords
):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["score"] >= 100
    assert resumo["novos_avisos"] == []
    assert resumo["ainda_atrasadas"] == []
    assert len(resumo["adiados"]) == 1
    assert resumo["adiados"][0]["nome"] == "Jiboia"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
@patch("motor.clima.deve_adiar_aviso", return_value=True)
def test_rodar_ciclo_adiado_nao_tira_planta_que_ja_esta_atrasada(
    mock_adiar, mock_clima_dia, mock_busca, mock_coords
):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 120)
    db.marcar_evento_calendario(conn, planta_id, "evento-existente")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    # já existe lembrete pra essa planta: adiar não deve escondê-la.
    assert resumo["adiados"] == []
    assert resumo["novos_avisos"] == []
    assert len(resumo["ainda_atrasadas"]) == 1
    assert resumo["ainda_atrasadas"][0]["evento_calendario_id"] == "evento-existente"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos")
@patch("motor.clima.clima_do_dia")
def test_rodar_ciclo_nao_deixa_score_negativo_apos_chuva_forte(
    mock_clima_dia, mock_busca, mock_coords
):
    mock_busca.return_value = {"daily": {"time": ["2026-08-18"]}}
    mock_clima_dia.return_value = {
        "et0": 1.0, "precipitacao_mm": 50.0, "probabilidade_chuva_pct": 90,
        "windspeed_10m_max": 5.0, "uv_index_max": 3.0,
        "umidade_relativa_pct": 90.0, "nebulosidade_pct": 90.0,
    }
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 2)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["score"] == 0
    assert resumo["atualizadas"][0]["score"] == 0

    cur = conn.cursor()
    cur.execute(
        "SELECT score_final FROM historico_scores WHERE planta_id = ?",
        (planta_id,),
    )
    score_final_historico = cur.fetchall()[0][0]
    # o histórico continua registrando o valor calculado (negativo), só o
    # score aplicado à planta é que tem piso em 0.
    assert score_final_historico < 0


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_busca_clima_uma_vez_por_cidade(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.inserir_planta(conn, {**PLANTA_EXEMPLO, "nome": "Babosa"})

    motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert mock_busca.call_count == 1


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_segunda_chamada_no_mesmo_dia_nao_altera_score(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    db.inserir_planta(conn, PLANTA_EXEMPLO)

    motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))
    score_apos_primeira = db.obter_planta(conn, "Jiboia")["score"]

    resumo_segunda = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert db.obter_planta(conn, "Jiboia")["score"] == score_apos_primeira
    assert resumo_segunda["atualizadas"] == []
    # a segunda chamada não deveria nem bater na API de clima de novo.
    assert mock_busca.call_count == 1


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_segunda_chamada_ainda_mostra_aviso_ja_existente(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 120)
    db.marcar_evento_calendario(conn, planta_id, "evento-existente")

    motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))
    resumo_segunda = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    # um lembrete que JÁ tem evento no calendário continua aparecendo numa
    # segunda chamada no mesmo dia — não é escondido.
    assert resumo_segunda["atualizadas"] == []
    assert resumo_segunda["novos_avisos"] == []
    assert len(resumo_segunda["ainda_atrasadas"]) == 1
    assert resumo_segunda["ainda_atrasadas"][0]["evento_calendario_id"] == "evento-existente"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_segunda_chamada_nao_reexpoe_planta_sem_evento_ainda(
    mock_clima_dia, mock_busca, mock_coords
):
    # Uma planta que cruzou 100 na primeira chamada de hoje mas ainda não
    # tem evento_calendario_id (porque o agente ainda não processou o
    # aviso, ou porque ela tinha sido adiada) não pode ser reclassificada
    # como "novo aviso" numa segunda chamada no mesmo dia: não dá pra saber
    # aqui se ela foi adiada ou não sem refazer o cálculo do clima, e
    # reexpor arriscaria criar um lembrete duplicado ou ignorar um
    # adiamento decidido mais cedo hoje (ver ledger, achado da revisão
    # final). O ciclo de amanhã reavalia isso do zero.
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)

    motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))
    resumo_segunda = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo_segunda["atualizadas"] == []
    assert resumo_segunda["novos_avisos"] == []
    assert resumo_segunda["adiados"] == []
    assert resumo_segunda["ainda_atrasadas"] == []


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
@patch("motor.clima.deve_adiar_aviso", return_value=True)
def test_rodar_ciclo_segunda_chamada_nao_desfaz_adiamento_da_primeira(
    mock_adiar, mock_clima_dia, mock_busca, mock_coords
):
    # Regressão do achado da revisão final: se a primeira chamada de hoje
    # adiou o aviso (foi pra "adiados", sem criar evento), uma segunda
    # chamada no mesmo dia não pode "vazar" essa planta pra novos_avisos —
    # isso derrubaria o próprio propósito do adiamento.
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)

    resumo_primeira = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))
    assert len(resumo_primeira["adiados"]) == 1

    resumo_segunda = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo_segunda["novos_avisos"] == []
    assert resumo_segunda["adiados"] == []
