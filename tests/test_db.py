import sqlite3

import db

PLANTA_EXEMPLO = {
    "nome": "Jiboia",
    "temperatura_ideal_c": 24.0,
    "umidade_ideal_pct": 60.0,
    "florescimento": "Raro",
    "crescimento": "Primavera",
    "crescimento2": "Verão",
    "poda": "Controle de tamanho",
    "replantio": "Primavera",
    "mudas": "Estacas em água",
    "epoca_mudas": "Primavera",
    "exposicao": 5,
    "cidade": "Sao Paulo, SP",
}


def _conexao_teste():
    conn = sqlite3.connect(":memory:")
    db.criar_schema(conn)
    return conn


def test_inserir_e_obter_planta():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    planta = db.obter_planta(conn, "Jiboia")

    assert planta["id"] == planta_id
    assert planta["nome"] == "Jiboia"
    assert planta["umidade_ideal_pct"] == 60.0
    assert planta["exposicao"] == 5
    assert planta["score"] == 0
    assert planta["evento_calendario_id"] is None


def test_obter_planta_inexistente_retorna_none():
    conn = _conexao_teste()
    assert db.obter_planta(conn, "Não existe") is None


def test_listar_plantas():
    conn = _conexao_teste()
    db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.inserir_planta(conn, {**PLANTA_EXEMPLO, "nome": "Babosa"})

    plantas = db.listar_plantas(conn)

    assert {p["nome"] for p in plantas} == {"Jiboia", "Babosa"}


def test_atualizar_score():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    db.atualizar_score(conn, planta_id, 42.5)

    assert db.obter_planta(conn, "Jiboia")["score"] == 42.5


def test_marcar_e_limpar_evento_calendario():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    db.marcar_evento_calendario(conn, planta_id, "evento-123")
    assert db.obter_planta(conn, "Jiboia")["evento_calendario_id"] == "evento-123"

    db.limpar_evento_calendario(conn, planta_id)
    assert db.obter_planta(conn, "Jiboia")["evento_calendario_id"] is None


def test_registrar_historico_score():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    db.registrar_historico_score(
        conn, planta_id, "2026-08-18",
        incremento_base=10, incremento_clima=3.5,
        score_final=13.5, et0=4.2, precipitacao_mm=0,
    )

    cur = conn.cursor()
    cur.execute("SELECT score_final, et0 FROM historico_scores WHERE planta_id = ?", (planta_id,))
    linha = cur.fetchall()[0]
    assert linha[0] == 13.5
    assert linha[1] == 4.2


def test_registrar_rega():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 130)

    db.registrar_rega(conn, planta_id, "2026-08-18", score_no_momento=130)

    cur = conn.cursor()
    cur.execute("SELECT score_no_momento FROM historico_regas WHERE planta_id = ?", (planta_id,))
    assert cur.fetchall()[0][0] == 130
