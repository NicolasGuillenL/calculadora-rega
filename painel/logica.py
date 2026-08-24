"""Lógica pura do painel (sem dependência do Streamlit) — fica separada de
`app.py` pra ser testável sem precisar rodar a interface."""


def calcular_status(planta):
    """Retorna (cor, texto) a partir do estado de rega da planta.

    `planta` é um dict no formato de `db.obter_planta`/`db.listar_plantas`
    (precisa ter as chaves `score`, `evento_calendario_id` e
    `evento_projetado_id`).
    `cor` é uma de "vermelho", "amarelo", "verde".
    """
    if planta["evento_calendario_id"]:
        return "vermelho", "Precisa regar agora"
    if planta["score"] >= 100:
        return "vermelho", "Precisa regar agora"
    if planta["evento_projetado_id"]:
        return "amarelo", "Previsão de regar em breve"
    return "verde", "Tranquila"
