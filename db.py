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
