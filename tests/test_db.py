import sqlite3

import pytest

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
    "retencao_substrato": "media",
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


def test_ja_processado_hoje_false_quando_nao_ha_historico():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    assert db.ja_processado_hoje(conn, planta_id, "2026-08-18") is False


def test_ja_processado_hoje_true_apos_registrar_historico():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.registrar_historico_score(
        conn, planta_id, "2026-08-18",
        incremento_base=10, incremento_clima=3.5,
        score_final=13.5, et0=4.2, precipitacao_mm=0,
    )

    assert db.ja_processado_hoje(conn, planta_id, "2026-08-18") is True
    assert db.ja_processado_hoje(conn, planta_id, "2026-08-19") is False


def test_conectar_sem_env_vars_gera_erro_claro(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="TURSO_DATABASE_URL"):
        db.conectar()


def test_atualizar_exposicao():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    db.atualizar_exposicao(conn, planta_id, 10)

    assert db.obter_planta(conn, "Jiboia")["exposicao"] == 10


def test_migrar_schema_v2_adiciona_colunas_novas():
    conn = sqlite3.connect(":memory:")
    # schema "antigo" (pré-v2), sem retencao_substrato nem evento_projetado_id
    conn.execute("""
        CREATE TABLE plantas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            temperatura_ideal_c REAL,
            umidade_ideal_pct REAL,
            florescimento TEXT,
            crescimento TEXT,
            crescimento2 TEXT,
            poda TEXT,
            replantio TEXT,
            mudas TEXT,
            epoca_mudas TEXT,
            exposicao INTEGER NOT NULL DEFAULT 5,
            cidade TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            ultima_rega TEXT,
            evento_calendario_id TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("INSERT INTO plantas (nome, cidade) VALUES (?, ?)", ("Jiboia", "Sao Paulo, SP"))
    conn.commit()

    db.migrar_schema_v2(conn)
    db.migrar_schema_v2(conn)  # idempotente: rodar de novo não pode quebrar

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["retencao_substrato"] == "media"
    assert planta["evento_projetado_id"] is None


def test_marcar_e_limpar_evento_projetado():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    db.marcar_evento_projetado(conn, planta_id, "projetado-123")
    assert db.obter_planta(conn, "Jiboia")["evento_projetado_id"] == "projetado-123"

    db.limpar_evento_projetado(conn, planta_id)
    assert db.obter_planta(conn, "Jiboia")["evento_projetado_id"] is None


def test_promover_evento_projetado_vira_confirmado_e_limpa_projetado():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.marcar_evento_projetado(conn, planta_id, "projetado-123")

    db.promover_evento_projetado(conn, planta_id, "projetado-123")

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["evento_calendario_id"] == "projetado-123"
    assert planta["evento_projetado_id"] is None


def test_atualizar_retencao_substrato():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    db.atualizar_retencao_substrato(conn, planta_id, "alta")

    assert db.obter_planta(conn, "Jiboia")["retencao_substrato"] == "alta"
