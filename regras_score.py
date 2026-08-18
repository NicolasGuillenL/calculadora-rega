"""Regras que definem quanto cada atributo da planta soma ao score por dia."""

NIVEIS_UMIDADE = [
    (65, float("inf"), 15),
    (45, 64.999, 10),
    (0, 44.999, 6),
]

FATOR_POR_NIVEL = {15: 1.5, 10: 1.0, 6: 0.5}

ESTACOES_POR_MES = {
    1: "Verão", 2: "Verão", 3: "Outono", 4: "Outono", 5: "Outono",
    6: "Inverno", 7: "Inverno", 8: "Inverno", 9: "Primavera",
    10: "Primavera", 11: "Primavera", 12: "Verão",
}


def nivel_umidade(umidade_pct):
    for minimo, maximo, valor in NIVEIS_UMIDADE:
        if minimo <= umidade_pct <= maximo:
            return valor
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
