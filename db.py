"""Camada de acesso ao banco (Turso/SQLite)."""
import os

import libsql_experimental as libsql
from dotenv import load_dotenv

load_dotenv()


def conectar():
    """Conecta no banco Turso configurado nas variáveis de ambiente."""
    url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    return libsql.connect(database=url, auth_token=token)


SCHEMA = """
CREATE TABLE IF NOT EXISTS plantas (
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
);

CREATE TABLE IF NOT EXISTS historico_regas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planta_id INTEGER NOT NULL REFERENCES plantas(id),
    data TEXT NOT NULL,
    score_no_momento REAL,
    origem TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS historico_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planta_id INTEGER NOT NULL REFERENCES plantas(id),
    data TEXT NOT NULL,
    incremento_base REAL,
    incremento_clima REAL,
    score_final REAL,
    et0 REAL,
    precipitacao_mm REAL,
    UNIQUE(planta_id, data)
);
"""

CAMPOS_PLANTA = [
    "nome", "temperatura_ideal_c", "umidade_ideal_pct", "florescimento",
    "crescimento", "crescimento2", "poda", "replantio", "mudas",
    "epoca_mudas", "exposicao", "cidade",
]


def criar_schema(conn):
    cur = conn.cursor()
    for instrucao in SCHEMA.strip().split(";"):
        instrucao = instrucao.strip()
        if instrucao:
            cur.execute(instrucao)
    conn.commit()


def _linha_para_dict(cursor, linha):
    colunas = [c[0] for c in cursor.description]
    return dict(zip(colunas, linha))


def inserir_planta(conn, planta):
    cur = conn.cursor()
    colunas = ", ".join(CAMPOS_PLANTA)
    marcadores = ", ".join("?" for _ in CAMPOS_PLANTA)
    valores = [planta.get(campo) for campo in CAMPOS_PLANTA]
    cur.execute(f"INSERT INTO plantas ({colunas}) VALUES ({marcadores})", valores)
    conn.commit()
    return cur.lastrowid


def obter_planta(conn, nome):
    cur = conn.cursor()
    cur.execute("SELECT * FROM plantas WHERE nome = ?", (nome,))
    linhas = cur.fetchall()
    if not linhas:
        return None
    return _linha_para_dict(cur, linhas[0])


def listar_plantas(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM plantas")
    linhas = cur.fetchall()
    return [_linha_para_dict(cur, linha) for linha in linhas]


def atualizar_score(conn, planta_id, novo_score):
    cur = conn.cursor()
    cur.execute("UPDATE plantas SET score = ? WHERE id = ?", (novo_score, planta_id))
    conn.commit()


def marcar_evento_calendario(conn, planta_id, evento_id):
    cur = conn.cursor()
    cur.execute("UPDATE plantas SET evento_calendario_id = ? WHERE id = ?", (evento_id, planta_id))
    conn.commit()


def limpar_evento_calendario(conn, planta_id):
    marcar_evento_calendario(conn, planta_id, None)


def registrar_historico_score(conn, planta_id, data, incremento_base, incremento_clima, score_final, et0, precipitacao_mm):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO historico_scores
           (planta_id, data, incremento_base, incremento_clima, score_final, et0, precipitacao_mm)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(planta_id, data) DO UPDATE SET
             incremento_base=excluded.incremento_base,
             incremento_clima=excluded.incremento_clima,
             score_final=excluded.score_final,
             et0=excluded.et0,
             precipitacao_mm=excluded.precipitacao_mm""",
        (planta_id, data, incremento_base, incremento_clima, score_final, et0, precipitacao_mm),
    )
    conn.commit()


def registrar_rega(conn, planta_id, data, score_no_momento):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO historico_regas (planta_id, data, score_no_momento) VALUES (?, ?, ?)",
        (planta_id, data, score_no_momento),
    )
    cur.execute("UPDATE plantas SET ultima_rega = ? WHERE id = ?", (data, planta_id))
    conn.commit()
