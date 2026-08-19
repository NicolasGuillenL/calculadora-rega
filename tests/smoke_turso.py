"""Rode manualmente (python3 tests/smoke_turso.py) para validar a conexão
com o Turso e confirmar que a API do driver é a esperada (cursor,
execute, fetchall, description)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db

conn = db.conectar()
cur = conn.cursor()
cur.execute("SELECT 1 AS um, 'ok' AS status")
linha = cur.fetchall()[0]
colunas = [c[0] for c in cur.description]
print(dict(zip(colunas, linha)))
conn.commit()
