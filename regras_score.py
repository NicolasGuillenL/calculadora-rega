"""Regras que definem quanto cada atributo da planta soma ao score por dia."""

FATOR_POR_NIVEL = {15: 1.5, 10: 1.0, 6: 0.5}

ESTACOES_POR_MES = {
    1: "Verão", 2: "Verão", 3: "Outono", 4: "Outono", 5: "Outono",
    6: "Inverno", 7: "Inverno", 8: "Inverno", 9: "Primavera",
    10: "Primavera", 11: "Primavera", 12: "Verão",
}


def nivel_umidade(umidade_pct):
    if umidade_pct >= 65:
        return 15
    if umidade_pct >= 45:
        return 10
    if umidade_pct >= 0:
        return 6
    raise ValueError(f"umidade fora do intervalo esperado: {umidade_pct}")


def fator_planta(umidade_pct):
    return FATOR_POR_NIVEL[nivel_umidade(umidade_pct)]


def estacao_atual(data):
    return ESTACOES_POR_MES[data.month]


def calcular_incremento_base(planta, data):
    incremento = nivel_umidade(planta["umidade_ideal_pct"])
    estacao = estacao_atual(data)
    if planta.get("crescimento") == estacao:
        incremento += 5
    if planta.get("crescimento2") == estacao:
        incremento += 5
    if planta.get("florescimento") == estacao:
        incremento += 3
    return incremento
