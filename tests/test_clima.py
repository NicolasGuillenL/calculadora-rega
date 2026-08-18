from unittest.mock import Mock, patch

import requests

import clima

RESPOSTA_API_EXEMPLO = {
    "daily": {
        "time": ["2026-08-17", "2026-08-18", "2026-08-19"],
        "et0_fao_evapotranspiration": [3.0, 4.0, 3.5],
        "precipitation_sum": [0.0, 0.0, 2.0],
        "precipitation_probability_max": [10, 20, 70],
        "windspeed_10m_max": [10.0, 25.0, 12.0],
        "uv_index_max": [5.0, 9.0, 6.0],
        "relative_humidity_2m_mean": [55.0, 35.0, 60.0],
        "cloudcover_mean": [20.0, 10.0, 80.0],
    }
}


def test_clima_do_dia_encontra_a_data_certa():
    dia = clima.clima_do_dia(RESPOSTA_API_EXEMPLO, "2026-08-18")

    assert dia["et0"] == 4.0
    assert dia["precipitacao_mm"] == 0.0
    assert dia["probabilidade_chuva_pct"] == 20
    assert dia["windspeed_10m_max"] == 25.0
    assert dia["uv_index_max"] == 9.0
    assert dia["umidade_relativa_pct"] == 35.0
    assert dia["nebulosidade_pct"] == 10.0


def test_clima_do_dia_trata_valores_nulos_da_api_sem_quebrar():
    resposta_com_nulos = {
        "daily": {
            "time": ["2026-08-18"],
            "et0_fao_evapotranspiration": [None],
            "precipitation_sum": [None],
            "precipitation_probability_max": [None],
            "windspeed_10m_max": [None],
            "uv_index_max": [None],
            "relative_humidity_2m_mean": [None],
            "cloudcover_mean": [None],
        }
    }

    dia = clima.clima_do_dia(resposta_com_nulos, "2026-08-18")

    assert dia["et0"] == 0.0
    assert dia["precipitacao_mm"] == 0.0
    assert dia["probabilidade_chuva_pct"] == 0
    assert dia["windspeed_10m_max"] == 0.0
    assert dia["uv_index_max"] == 0.0
    assert dia["umidade_relativa_pct"] == 0.0
    assert dia["nebulosidade_pct"] == 0.0


@patch("clima.requests.get")
def test_buscar_dados_climaticos_faz_request_correto(mock_get):
    mock_resposta = Mock()
    mock_resposta.json.return_value = RESPOSTA_API_EXEMPLO
    mock_resposta.raise_for_status.return_value = None
    mock_get.return_value = mock_resposta

    resultado = clima.buscar_dados_climaticos(-23.5, -46.6)

    assert resultado == RESPOSTA_API_EXEMPLO
    args, kwargs = mock_get.call_args
    assert kwargs["params"]["latitude"] == -23.5
    assert kwargs["params"]["longitude"] == -46.6


@patch("clima.time.sleep")
@patch("clima.requests.get")
def test_buscar_dados_climaticos_tenta_de_novo_apos_falha_de_rede(mock_get, mock_sleep):
    mock_resposta_ok = Mock()
    mock_resposta_ok.json.return_value = RESPOSTA_API_EXEMPLO
    mock_resposta_ok.raise_for_status.return_value = None
    mock_get.side_effect = [
        requests.exceptions.ReadTimeout("timeout simulado"),
        mock_resposta_ok,
    ]

    resultado = clima.buscar_dados_climaticos(-23.5, -46.6)

    assert resultado == RESPOSTA_API_EXEMPLO
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()


@patch("clima.time.sleep")
@patch("clima.requests.get")
def test_buscar_dados_climaticos_desiste_apos_esgotar_tentativas(mock_get, mock_sleep):
    mock_get.side_effect = requests.exceptions.ReadTimeout("timeout simulado")

    try:
        clima.buscar_dados_climaticos(-23.5, -46.6)
        assert False, "deveria ter levantado a exceção"
    except requests.exceptions.ReadTimeout:
        pass

    assert mock_get.call_count == clima.TENTATIVAS_REQUEST
    assert mock_sleep.call_count == clima.TENTATIVAS_REQUEST - 1


def _clima_seco_e_quente():
    return {
        "et0": 5.0, "precipitacao_mm": 0.0, "probabilidade_chuva_pct": 5,
        "windspeed_10m_max": 25.0, "uv_index_max": 9.0,
        "umidade_relativa_pct": 30.0, "nebulosidade_pct": 10.0,
    }


def test_incremento_clima_planta_totalmente_exposta_dia_seco_aumenta_score():
    planta = {"umidade_ideal_pct": 70, "exposicao": 10}
    incremento = clima.calcular_incremento_clima(planta, _clima_seco_e_quente())
    assert incremento > 0


def test_incremento_clima_planta_dentro_de_casa_sente_bem_menos_o_sol():
    planta_exposta = {"umidade_ideal_pct": 70, "exposicao": 10}
    planta_indoor = {"umidade_ideal_pct": 70, "exposicao": 0}

    incremento_exposta = clima.calcular_incremento_clima(planta_exposta, _clima_seco_e_quente())
    incremento_indoor = clima.calcular_incremento_clima(planta_indoor, _clima_seco_e_quente())

    assert incremento_indoor < incremento_exposta


def test_incremento_clima_planta_que_precisa_de_pouca_agua_sofre_menos_com_sol():
    planta_precisa_muita_agua = {"umidade_ideal_pct": 70, "exposicao": 10}
    planta_precisa_pouca_agua = {"umidade_ideal_pct": 30, "exposicao": 10}

    incremento_alta = clima.calcular_incremento_clima(planta_precisa_muita_agua, _clima_seco_e_quente())
    incremento_baixa = clima.calcular_incremento_clima(planta_precisa_pouca_agua, _clima_seco_e_quente())

    assert incremento_baixa < incremento_alta


def test_chuva_forte_reduz_score_de_planta_exposta():
    planta = {"umidade_ideal_pct": 60, "exposicao": 10}
    clima_com_chuva = {
        "et0": 3.0, "precipitacao_mm": 10.0, "probabilidade_chuva_pct": 90,
        "windspeed_10m_max": 10.0, "uv_index_max": 3.0,
        "umidade_relativa_pct": 80.0, "nebulosidade_pct": 90.0,
    }
    incremento = clima.calcular_incremento_clima(planta, clima_com_chuva)
    assert incremento < 0


def test_chuva_nao_afeta_diretamente_planta_dentro_de_casa():
    planta = {"umidade_ideal_pct": 60, "exposicao": 0}
    clima_com_chuva = {
        "et0": 3.0, "precipitacao_mm": 10.0, "probabilidade_chuva_pct": 90,
        "windspeed_10m_max": 10.0, "uv_index_max": 3.0,
        "umidade_relativa_pct": 80.0, "nebulosidade_pct": 90.0,
    }
    incremento = clima.calcular_incremento_clima(planta, clima_com_chuva)
    # não pode zerar/reduzir drasticamente como aconteceria numa planta exposta
    assert incremento >= -3


def test_deve_adiar_aviso_quando_score_alto_e_chuva_provavel():
    clima_hoje = {"probabilidade_chuva_pct": 80}
    assert clima.deve_adiar_aviso(95, clima_hoje) is True


def test_nao_deve_adiar_aviso_quando_score_baixo():
    clima_hoje = {"probabilidade_chuva_pct": 80}
    assert clima.deve_adiar_aviso(50, clima_hoje) is False


def test_nao_deve_adiar_aviso_quando_chuva_improvavel():
    clima_hoje = {"probabilidade_chuva_pct": 10}
    assert clima.deve_adiar_aviso(95, clima_hoje) is False
