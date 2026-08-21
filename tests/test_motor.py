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


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
@patch("motor.clima.deve_adiar_aviso", return_value=True)
def test_rodar_ciclo_entra_em_adiados_quando_cruzaria_100(
    mock_adiar, mock_clima_dia, mock_busca, mock_coords
):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)  # 95 + 11 (base+clima neutro) = 106

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo["novos_avisos"] == []
    assert resumo["ainda_atrasadas"] == []
    assert len(resumo["adiados"]) == 1
    assert resumo["adiados"][0]["nome"] == "Jiboia"
    assert resumo["adiados"][0]["score"] >= 100
    # o score aplicado à planta continua congelado (comportamento já testado
    # acima) — aqui só confirmamos que ela é reportada como "adiada"
    assert db.obter_planta(conn, "Jiboia")["score"] == 95


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_novo_aviso_confirma_evento_projetado(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)
    db.marcar_evento_projetado(conn, planta_id, "previsao-999")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["novos_avisos"]) == 1
    assert resumo["novos_avisos"][0]["evento_projetado_id"] == "previsao-999"


# --- projeções (agenda proativa) ---------------------------------------

RESPOSTA_SECA = {
    "daily": {
        "time": ["2026-08-18", "2026-08-19", "2026-08-20"],
        "et0_fao_evapotranspiration": [5.0, 5.0, 5.0],
        "precipitation_sum": [0.0, 0.0, 0.0],
        "precipitation_probability_max": [10, 10, 10],
        "windspeed_10m_max": [5.0, 5.0, 5.0],
        "uv_index_max": [3.0, 3.0, 3.0],
        "relative_humidity_2m_mean": [55.0, 55.0, 55.0],
        "cloudcover_mean": [20.0, 20.0, 20.0],
    }
}

RESPOSTA_CHUVA_FUTURA = {
    "daily": {
        "time": ["2026-08-18", "2026-08-19", "2026-08-20"],
        "et0_fao_evapotranspiration": [5.0, 5.0, 5.0],
        "precipitation_sum": [0.0, 30.0, 30.0],
        "precipitation_probability_max": [10, 80, 80],
        "windspeed_10m_max": [5.0, 5.0, 5.0],
        "uv_index_max": [3.0, 3.0, 3.0],
        "relative_humidity_2m_mean": [55.0, 55.0, 55.0],
        "cloudcover_mean": [20.0, 20.0, 20.0],
    }
}


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value=RESPOSTA_SECA)
def test_rodar_ciclo_projeta_criar_quando_vai_cruzar_100_na_janela(mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 70)  # some+12.5/dia sem chuva cruza 100 em 2 dias

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo["novos_avisos"] == []
    assert len(resumo["projecoes"]) == 1
    projecao = resumo["projecoes"][0]
    assert projecao["nome"] == "Jiboia"
    assert projecao["acao"] == "criar"
    assert projecao["data_prevista"] == "2026-08-20"
    assert "evento_projetado_id" not in projecao


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value=RESPOSTA_SECA)
def test_rodar_ciclo_projeta_atualizar_quando_ja_tem_evento_projetado(mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 70)
    db.marcar_evento_projetado(conn, planta_id, "previsao-abc")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["projecoes"]) == 1
    projecao = resumo["projecoes"][0]
    assert projecao["acao"] == "atualizar"
    assert projecao["evento_projetado_id"] == "previsao-abc"
    assert projecao["data_prevista"] == "2026-08-20"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value=RESPOSTA_CHUVA_FUTURA)
def test_rodar_ciclo_projeta_cancelar_quando_chuva_muda_previsao(mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 82.5)  # some 12.5 hoje = 95, mas chuva futura segura
    db.marcar_evento_projetado(conn, planta_id, "previsao-abc")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo["novos_avisos"] == []
    assert len(resumo["projecoes"]) == 1
    projecao = resumo["projecoes"][0]
    assert projecao["acao"] == "cancelar"
    assert projecao["evento_projetado_id"] == "previsao-abc"
    assert "data_prevista" not in projecao


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value=RESPOSTA_SECA)
def test_rodar_ciclo_sem_projecao_quando_nao_vai_cruzar_e_nunca_teve_evento(mock_busca, mock_coords):
    conn = _conexao_teste()
    db.inserir_planta(conn, PLANTA_EXEMPLO)  # score 0, longe de cruzar 100 em 2 dias

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo["projecoes"] == []
