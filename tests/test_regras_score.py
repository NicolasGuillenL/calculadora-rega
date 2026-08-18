import datetime

import regras_score


def test_nivel_umidade_alta():
    assert regras_score.nivel_umidade(70) == 15
    assert regras_score.nivel_umidade(65) == 15


def test_nivel_umidade_media():
    assert regras_score.nivel_umidade(60) == 10
    assert regras_score.nivel_umidade(45) == 10


def test_nivel_umidade_baixa():
    assert regras_score.nivel_umidade(40) == 6
    assert regras_score.nivel_umidade(0) == 6


def test_fator_planta_correlaciona_com_nivel_umidade():
    assert regras_score.fator_planta(70) == 1.5
    assert regras_score.fator_planta(50) == 1.0
    assert regras_score.fator_planta(30) == 0.5


def test_estacao_atual():
    assert regras_score.estacao_atual(datetime.date(2026, 1, 15)) == "Verão"
    assert regras_score.estacao_atual(datetime.date(2026, 4, 1)) == "Outono"
    assert regras_score.estacao_atual(datetime.date(2026, 7, 1)) == "Inverno"
    assert regras_score.estacao_atual(datetime.date(2026, 10, 1)) == "Primavera"


def test_incremento_base_so_umidade():
    planta = {"umidade_ideal_pct": 60, "crescimento": None, "crescimento2": None, "florescimento": None}
    assert regras_score.calcular_incremento_base(planta, datetime.date(2026, 8, 18)) == 10


def test_incremento_base_com_crescimento_ativo():
    # agosto = Inverno
    planta = {"umidade_ideal_pct": 60, "crescimento": "Inverno", "crescimento2": None, "florescimento": None}
    assert regras_score.calcular_incremento_base(planta, datetime.date(2026, 8, 18)) == 15


def test_incremento_base_com_todas_as_epocas_batendo():
    planta = {"umidade_ideal_pct": 70, "crescimento": "Inverno", "crescimento2": "Inverno", "florescimento": "Inverno"}
    # 15 (umidade) + 5 (crescimento) + 5 (crescimento2) + 3 (florescimento)
    assert regras_score.calcular_incremento_base(planta, datetime.date(2026, 8, 18)) == 28
