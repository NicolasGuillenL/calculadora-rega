from painel import logica


def test_status_vermelho_quando_tem_evento_calendario():
    planta = {"evento_calendario_id": "evento-1", "evento_projetado_id": None}

    cor, texto = logica.calcular_status(planta)

    assert cor == "vermelho"
    assert texto == "Precisa regar agora"


def test_status_amarelo_quando_tem_evento_projetado():
    planta = {"evento_calendario_id": None, "evento_projetado_id": "proj-1"}

    cor, texto = logica.calcular_status(planta)

    assert cor == "amarelo"
    assert texto == "Previsão de regar em breve"


def test_status_verde_quando_nao_tem_nenhum_evento():
    planta = {"evento_calendario_id": None, "evento_projetado_id": None}

    cor, texto = logica.calcular_status(planta)

    assert cor == "verde"
    assert texto == "Tranquila"


def test_status_vermelho_tem_prioridade_sobre_projetado():
    # Não deveria acontecer na prática (marcar_evento_projetado só roda
    # quando não há evento confirmado), mas se os dois estiverem
    # preenchidos ao mesmo tempo, "precisa regar agora" vence.
    planta = {"evento_calendario_id": "evento-1", "evento_projetado_id": "proj-1"}

    cor, texto = logica.calcular_status(planta)

    assert cor == "vermelho"
