import sqlite3
from pathlib import Path

import db
import migracao

FIXTURE = Path(__file__).parent / "fixtures" / "Bd_Plantas_exemplo.ipynb"


def test_carregar_dados_do_notebook_corrige_o_bug_do_estacoes():
    plantas, estacoes = migracao.carregar_dados_do_notebook(str(FIXTURE))

    assert "Jiboia" in plantas
    assert plantas["Jiboia"]["Temperatura_ideal"] == "24°C"
    assert estacoes["janeiro"] == "Verão"


def test_migrar_insere_plantas_no_banco():
    conn = sqlite3.connect(":memory:")
    db.criar_schema(conn)

    inseridas = migracao.migrar(conn, str(FIXTURE), cidade_padrao="Sao Paulo, SP")

    assert inseridas == ["Jiboia"]
    planta = db.obter_planta(conn, "Jiboia")
    assert planta["temperatura_ideal_c"] == 24.0
    assert planta["umidade_ideal_pct"] == 60.0
    assert planta["florescimento"] == "Raro"
    assert planta["cidade"] == "Sao Paulo, SP"
    assert planta["exposicao"] == 5
