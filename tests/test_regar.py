import datetime
import runpy
import sqlite3
import sys
from unittest.mock import patch

import pytest

import db
import regar

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
    "retencao_substrato": "media",
    "cidade": "Sao Paulo, SP",
}


def _conexao_teste():
    conn = sqlite3.connect(":memory:")
    db.criar_schema(conn)
    return conn


def test_regar_zera_score_e_registra_historico():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 135)
    db.marcar_evento_calendario(conn, planta_id, "evento-abc")

    resultado = regar.regar(conn, "Jiboia", hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["score"] == 0
    assert planta["ultima_rega"] == "2026-08-18"
    assert planta["evento_calendario_id"] is None
    assert resultado == {
        "nome": "Jiboia",
        "score_anterior": 135,
        "evento_calendario_id_removido": "evento-abc",
        "evento_projetado_id_removido": None,
    }

    cur = conn.cursor()
    cur.execute("SELECT score_no_momento FROM historico_regas WHERE planta_id = ?", (planta_id,))
    assert cur.fetchall()[0][0] == 135


def test_regar_planta_inexistente_gera_erro():
    conn = _conexao_teste()
    with pytest.raises(ValueError):
        regar.regar(conn, "Não existe")


def test_regar_limpa_evento_confirmado_e_projetado_ao_mesmo_tempo():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 135)
    db.marcar_evento_calendario(conn, planta_id, "evento-confirmado")
    db.marcar_evento_projetado(conn, planta_id, "evento-projetado")

    resultado = regar.regar(conn, "Jiboia", hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["evento_calendario_id"] is None
    assert planta["evento_projetado_id"] is None
    assert resultado["evento_calendario_id_removido"] == "evento-confirmado"
    assert resultado["evento_projetado_id_removido"] == "evento-projetado"


def test_cli_avisa_sobre_os_dois_eventos_pendentes(capsys):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 135)
    db.marcar_evento_calendario(conn, planta_id, "evento-confirmado")
    db.marcar_evento_projetado(conn, planta_id, "evento-projetado")

    with patch("db.conectar", return_value=conn), patch.object(sys, "argv", ["regar.py", "Jiboia"]):
        runpy.run_module("regar", run_name="__main__")

    saida = capsys.readouterr().out
    assert "evento-confirmado" in saida
    assert "evento-projetado" in saida
    assert "Calendar" in saida


def test_cli_avisa_que_evento_do_calendario_precisa_ser_apagado(capsys):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 135)
    db.marcar_evento_calendario(conn, planta_id, "evento-abc")

    with patch("db.conectar", return_value=conn), patch.object(sys, "argv", ["regar.py", "Jiboia"]):
        runpy.run_module("regar", run_name="__main__")

    saida = capsys.readouterr().out
    assert "evento-abc" in saida
    assert "Calendar" in saida
