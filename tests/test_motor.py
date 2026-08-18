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
def test_rodar_ciclo_adiado_grava_historico_calculado_mas_nao_muda_score(
    mock_adiar, mock_clima_dia, mock_busca, mock_coords
):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 50)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    # score na tabela plantas não deve mudar, pois o aviso foi adiado
    assert planta["score"] == 50
    assert resumo["atualizadas"][0]["score"] == 50

    cur = conn.cursor()
    cur.execute(
        "SELECT score_final FROM historico_scores WHERE planta_id = ?",
        (planta_id,),
    )
    score_final_historico = cur.fetchall()[0][0]
    # o histórico deve registrar o valor CALCULADO (score projetado),
    # não o valor efetivamente aplicado (que ficou igual ao anterior)
    assert score_final_historico != 50
    assert score_final_historico > 50
