"""Integração com a API gratuita do Open-Meteo e cálculo do modificador climático."""
import time

import requests

import regras_score

# A automação roda 1x/dia, sem supervisão — uma falha de rede passageira não
# pode derrubar o ciclo inteiro. Poucas tentativas com espera curta bastam
# pra absorver instabilidade momentânea da API sem atrasar o ciclo por muito
# tempo.
TENTATIVAS_REQUEST = 3
ESPERA_ENTRE_TENTATIVAS_S = 2


def _get_com_retry(url, params, tentativas=TENTATIVAS_REQUEST, espera_s=ESPERA_ENTRE_TENTATIVAS_S):
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as erro:
            ultimo_erro = erro
            if tentativa < tentativas:
                time.sleep(espera_s)
    raise ultimo_erro

VARIAVEIS_DIARIAS = [
    "et0_fao_evapotranspiration",
    "precipitation_sum",
    "precipitation_probability_max",
    "windspeed_10m_max",
    "uv_index_max",
    "relative_humidity_2m_mean",
    "cloudcover_mean",
]

LIMIAR_VENTO_KMH = 20
LIMIAR_UV_ALTO = 8
LIMIAR_UMIDADE_BAIXA = 40
LIMIAR_UMIDADE_ALTA = 80
LIMIAR_NEBULOSIDADE_ALTA = 70
FATOR_CHUVA = 5
PROBABILIDADE_CHUVA_ADIA = 60
SCORE_PROJETADO_ADIA = 90

# Alívio de umidade do ar para plantas indoor quando chove lá fora: pequeno e
# limitado, para nunca se aproximar do efeito que a chuva teria numa planta
# exposta (ver LIMIAR_ALIVIO_CHUVA_INDOOR_MAX abaixo).
FATOR_ALIVIO_CHUVA_INDOOR = 0.5
LIMIAR_ALIVIO_CHUVA_INDOOR_MAX = 3.0

FATOR_RETENCAO = {"alta": 0.6, "media": 1.0, "baixa": 1.3}


def geocode_cidade(cidade):
    resp = _get_com_retry(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": cidade, "count": 1, "language": "pt"},
    )
    resultados = resp.json().get("results")
    if not resultados:
        raise ValueError(f"Não encontrei coordenadas para a cidade '{cidade}'.")
    return resultados[0]["latitude"], resultados[0]["longitude"]


def buscar_dados_climaticos(lat, lon, dias_passados=1, dias_futuros=3):
    resp = _get_com_retry(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(VARIAVEIS_DIARIAS),
            "timezone": "auto",
            "past_days": dias_passados,
            "forecast_days": dias_futuros,
        },
    )
    return resp.json()


def clima_do_dia(resposta_api, data_iso):
    diario = resposta_api["daily"]
    idx = diario["time"].index(data_iso)
    return {
        "et0": diario["et0_fao_evapotranspiration"][idx] or 0.0,
        "precipitacao_mm": diario["precipitation_sum"][idx] or 0.0,
        "probabilidade_chuva_pct": diario["precipitation_probability_max"][idx] or 0,
        "windspeed_10m_max": diario["windspeed_10m_max"][idx] or 0.0,
        "uv_index_max": diario["uv_index_max"][idx] or 0.0,
        "umidade_relativa_pct": diario["relative_humidity_2m_mean"][idx] or 0.0,
        "nebulosidade_pct": diario["cloudcover_mean"][idx] or 0.0,
    }


def calcular_incremento_clima(planta, clima_hoje):
    exposicao_fator = planta["exposicao"] / 10
    fator = regras_score.fator_planta(planta["umidade_ideal_pct"])
    fator_retencao = FATOR_RETENCAO[planta.get("retencao_substrato", "media")]

    secagem = clima_hoje["et0"] * fator * fator_retencao * exposicao_fator

    if exposicao_fator > 0:
        if clima_hoje["windspeed_10m_max"] >= LIMIAR_VENTO_KMH:
            secagem *= 1.15
        if clima_hoje["uv_index_max"] >= LIMIAR_UV_ALTO:
            secagem *= 1.15

    if clima_hoje["umidade_relativa_pct"] < LIMIAR_UMIDADE_BAIXA:
        secagem *= 1.10
    elif clima_hoje["umidade_relativa_pct"] > LIMIAR_UMIDADE_ALTA:
        secagem *= 0.90

    if clima_hoje["nebulosidade_pct"] > LIMIAR_NEBULOSIDADE_ALTA and clima_hoje["precipitacao_mm"] == 0:
        secagem *= 0.90

    if exposicao_fator == 0:
        # dentro de casa: chuva não molha a planta, só um alívio pequeno de
        # umidade do ar. O cap fica estritamente abaixo de 3 para garantir
        # que o efeito nunca chegue perto do que a chuva causaria numa
        # planta exposta.
        efeito_chuva = min(
            LIMIAR_ALIVIO_CHUVA_INDOOR_MAX,
            clima_hoje["precipitacao_mm"] * FATOR_ALIVIO_CHUVA_INDOOR,
        )
    else:
        efeito_chuva = clima_hoje["precipitacao_mm"] * FATOR_CHUVA * exposicao_fator

    return secagem - efeito_chuva


def deve_adiar_aviso(score_projetado, clima_hoje):
    return (
        score_projetado >= SCORE_PROJETADO_ADIA
        and clima_hoje["probabilidade_chuva_pct"] >= PROBABILIDADE_CHUVA_ADIA
    )
