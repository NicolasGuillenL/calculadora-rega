"""Camada de acesso ao banco (Turso/SQLite)."""
import os

import libsql_experimental as libsql
from dotenv import load_dotenv

load_dotenv()


def conectar():
    """Conecta no banco Turso configurado nas variáveis de ambiente."""
    try:
        url = os.environ["TURSO_DATABASE_URL"]
        token = os.environ["TURSO_AUTH_TOKEN"]
    except KeyError as erro:
        variavel = erro.args[0]
        raise RuntimeError(
            f"Variável de ambiente '{variavel}' não está definida. "
            "Configure TURSO_DATABASE_URL e TURSO_AUTH_TOKEN (por exemplo, "
            "num arquivo .env ou nas variáveis exportadas pela tarefa "
            "agendada) antes de conectar no banco."
        ) from erro
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
    retencao_substrato TEXT NOT NULL DEFAULT 'media',
    evento_projetado_id TEXT,
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

CREATE TABLE IF NOT EXISTS eventos_pendentes_limpeza (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Mantém em sincronia (conceitualmente) com as chaves de clima.FATOR_RETENCAO
# — não importamos `clima` aqui pra não criar uma dependência às avessas
# (clima.py não precisa saber nada sobre db.py).
VALORES_RETENCAO_VALIDOS = {"alta", "media", "baixa"}

CAMPOS_PLANTA = [
    "nome", "temperatura_ideal_c", "umidade_ideal_pct", "florescimento",
    "crescimento", "crescimento2", "poda", "replantio", "mudas",
    "epoca_mudas", "exposicao", "cidade", "retencao_substrato",
]


def criar_schema(conn):
    cur = conn.cursor()
    for instrucao in SCHEMA.strip().split(";"):
        instrucao = instrucao.strip()
        if instrucao:
            cur.execute(instrucao)
    conn.commit()
    migrar_schema_v2(conn)


def migrar_schema_v2(conn):
    """Adiciona as colunas da v2 (retencao_substrato, evento_projetado_id) a
    um banco criado antes delas existirem. Idempotente: rodar mais de uma
    vez não quebra, mesmo que as colunas já existam (CREATE TABLE já as
    inclui em bancos novos, então isso vira um no-op nesse caso)."""
    cur = conn.cursor()
    alteracoes = [
        "ALTER TABLE plantas ADD COLUMN retencao_substrato TEXT NOT NULL DEFAULT 'media'",
        "ALTER TABLE plantas ADD COLUMN evento_projetado_id TEXT",
    ]
    for instrucao in alteracoes:
        try:
            cur.execute(instrucao)
        except Exception as erro:
            if "duplicate column" not in str(erro).lower():
                raise
    conn.commit()


def _linha_para_dict(cursor, linha):
    colunas = [c[0] for c in cursor.description]
    return dict(zip(colunas, linha))


def inserir_planta(conn, planta):
    cur = conn.cursor()
    colunas = ", ".join(CAMPOS_PLANTA)
    marcadores = ", ".join("?" for _ in CAMPOS_PLANTA)
    valores = tuple(planta.get(campo) for campo in CAMPOS_PLANTA)
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


def marcar_evento_projetado(conn, planta_id, evento_id):
    cur = conn.cursor()
    cur.execute("UPDATE plantas SET evento_projetado_id = ? WHERE id = ?", (evento_id, planta_id))
    conn.commit()


def limpar_evento_projetado(conn, planta_id):
    marcar_evento_projetado(conn, planta_id, None)


def promover_evento_projetado(conn, planta_id, evento_id):
    """Confirma um evento que estava projetado: ele vira o evento oficial
    (evento_calendario_id) e o campo de projeção é limpo — mesmo evento no
    Calendar, sem criar um novo nem cancelar o antigo."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE plantas SET evento_calendario_id = ?, evento_projetado_id = NULL WHERE id = ?",
        (evento_id, planta_id),
    )
    conn.commit()


def atualizar_retencao_substrato(conn, planta_id, novo_valor):
    if novo_valor not in VALORES_RETENCAO_VALIDOS:
        raise ValueError(
            f"retencao_substrato inválido: '{novo_valor}'. Use um de: alta, media, baixa."
        )
    cur = conn.cursor()
    cur.execute("UPDATE plantas SET retencao_substrato = ? WHERE id = ?", (novo_valor, planta_id))
    conn.commit()


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


def ja_processado_hoje(conn, planta_id, data):
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM historico_scores WHERE planta_id = ? AND data = ?",
        (planta_id, data),
    )
    return cur.fetchall() != []


def registrar_rega(conn, planta_id, data, score_no_momento):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO historico_regas (planta_id, data, score_no_momento) VALUES (?, ?, ?)",
        (planta_id, data, score_no_momento),
    )
    cur.execute("UPDATE plantas SET ultima_rega = ? WHERE id = ?", (data, planta_id))
    conn.commit()


def atualizar_exposicao(conn, planta_id, nova_exposicao):
    cur = conn.cursor()
    cur.execute("UPDATE plantas SET exposicao = ? WHERE id = ?", (nova_exposicao, planta_id))
    conn.commit()


def enfileirar_evento_pendente_limpeza(conn, evento_id):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO eventos_pendentes_limpeza (evento_id) VALUES (?)",
        (evento_id,),
    )
    conn.commit()


def listar_eventos_pendentes_limpeza(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM eventos_pendentes_limpeza")
    linhas = cur.fetchall()
    return [_linha_para_dict(cur, linha) for linha in linhas]


def remover_evento_pendente_limpeza(conn, pendente_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM eventos_pendentes_limpeza WHERE id = ?", (pendente_id,))
    conn.commit()
