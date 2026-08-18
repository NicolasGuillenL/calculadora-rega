# Calculadora de Rega de Planta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o dict do notebook `Bd_Plantas.ipynb` por um sistema de score de rega (0-100+) por planta, persistido no Turso, atualizado 1x/dia por uma tarefa agendada que consulta o clima (Open-Meteo) e cria/remove lembretes no Google Calendar.

**Architecture:** Módulos Python pequenos e testáveis (`db.py`, `regras_score.py`, `clima.py`, `motor.py`, `regar.py`, `migracao.py`, `config.py`) rodando num repositório Git público no GitHub. `motor.py`/`main.py` fazem só o cálculo puro e devolvem um resumo em JSON — a criação/remoção de eventos no Google Calendar e o envio de notificações acontecem na camada do agente (a tarefa agendada do Claude), que lê esse JSON e usa suas próprias ferramentas de Calendar/notificação. Isso existe porque as ferramentas de Google Calendar só existem dentro de uma sessão do Claude, não dentro de um script Python isolado.

**Tech Stack:** Python 3, `libsql-experimental` (cliente Turso, API compatível com `sqlite3`), `requests` (HTTP pro Open-Meteo), `pytest` + `unittest.mock` (testes), `python-dotenv` (variáveis de ambiente locais).

**Spec:** `docs/superpowers/specs/2026-08-18-calculadora-rega-design.md`

## Global Constraints

- Score não tem teto — passar de 100 indica atraso, quanto maior mais atrasada a rega.
- `exposicao` só assume os valores 0, 5 ou 10.
- Clima vem só do Open-Meteo (gratuito, sem chave de API).
- `et0_fao_evapotranspiration` é o eixo principal do modificador climático; vento/UV/umidade/nebulosidade são ajustes de ~10-15%, nunca o termo dominante.
- Banco de dados: Turso (SQLite hospedado) — mesmo dialeto SQL do SQLite, então os testes podem rodar contra `sqlite3` em memória sem precisar de rede.
- Toda função de `db.py`, `regras_score.py`, `clima.py` (exceto as que fazem I/O de rede/banco) deve ser testável isoladamente, sem rede e sem Turso real.
- Sem placeholders: todo commit deixa o projeto num estado que roda.

---

## Estrutura de arquivos

```
calculadora-rega/
  requirements.txt
  .gitignore
  .env.example
  pytest.ini
  config.py
  db.py
  regras_score.py
  clima.py
  motor.py
  regar.py
  migracao.py
  main.py
  tests/
    test_regras_score.py
    test_clima.py
    test_db.py
    test_motor.py
    test_regar.py
    test_migracao.py
  docs/superpowers/specs/2026-08-18-calculadora-rega-design.md   (já existe)
  docs/superpowers/plans/2026-08-18-calculadora-rega.md          (este arquivo)
```

---

### Task 1: Projeto base + conta Turso + conexão via Python

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pytest.ini`
- Create: `db.py` (só `conectar()` por enquanto)
- Create: `tests/smoke_turso.py` (script manual, não é teste pytest)

**Interfaces:**
- Produces: `db.conectar() -> Connection` (objeto compatível com DB-API2: `.cursor()`, `.execute()`, `.commit()`; cursor com `.execute()`, `.fetchall()`, `.description`)

- [ ] **Step 1: Criar a conta e o banco no Turso**

Isso precisa ser feito pelo usuário (Nero), fora do código:

1. Acesse https://turso.tech e crie uma conta gratuita (dá pra usar login do GitHub).
2. Crie um banco de dados novo (qualquer nome, ex: `calculadora-rega`).
3. No painel do banco, gere uma "Database URL" (algo como `libsql://calculadora-rega-<usuario>.turso.io`) e um "Auth Token".
4. Guarde os dois valores — vão entrar num arquivo `.env` local (nunca commitado no Git).

- [ ] **Step 2: Criar `requirements.txt`**

```
requests>=2.32,<3
libsql-experimental>=0.0.30
python-dotenv>=1.0,<2
pytest>=8.3,<9
```

(sem fixar o patch exato do `libsql-experimental` — o pacote muda de versão com frequência; `pip install` vai pegar a mais recente compatível.)

- [ ] **Step 3: Instalar as dependências**

Run: `pip install -r requirements.txt --break-system-packages`
Expected: instalação sem erro. Se `libsql-experimental` falhar ou o nome do pacote tiver mudado, consulte https://docs.turso.tech/sdk/python/quickstart pelo nome/API atual e ajuste o Step 6 abaixo — o resto do projeto só chama `db.conectar()`, então uma mudança de SDK fica isolada nesse único ponto.

- [ ] **Step 4: Criar `.gitignore`**

```
.env
__pycache__/
*.pyc
.pytest_cache/
cidade_cache.json
```

- [ ] **Step 5: Criar `.env.example` (documentação, sem valores reais) e seu `.env` local (com os valores reais, não commitado)**

`.env.example`:
```
TURSO_DATABASE_URL=libsql://seu-banco.turso.io
TURSO_AUTH_TOKEN=coloque-seu-token-aqui
CIDADE_PADRAO=Sao Paulo, SP
```

Copie para `.env` e preencha com os valores reais do Step 1.

- [ ] **Step 6: Criar `db.py` com a função de conexão**

```python
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
```

- [ ] **Step 7: Criar `pytest.ini`**

```ini
[pytest]
testpaths = tests
```

- [ ] **Step 8: Escrever e rodar o smoke test manual (não é parte da suíte pytest — é só pra validar a conexão real com o Turso)**

`tests/smoke_turso.py`:
```python
"""Rode manualmente (python3 tests/smoke_turso.py) para validar a conexão
com o Turso e confirmar que a API do driver é a esperada (cursor,
execute, fetchall, description)."""
import db

conn = db.conectar()
cur = conn.cursor()
cur.execute("SELECT 1 AS um, 'ok' AS status")
linha = cur.fetchall()[0]
colunas = [c[0] for c in cur.description]
print(dict(zip(colunas, linha)))
conn.commit()
```

Run: `python3 tests/smoke_turso.py`
Expected: imprime `{'um': 1, 'status': 'ok'}` sem erro. Se o formato de `cur.description` ou `fetchall()` vier diferente do DB-API2 padrão, anote a diferença — ela só vai importar no Task 2, onde escrevemos o wrapper que todo o resto do projeto usa.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .gitignore .env.example pytest.ini db.py tests/smoke_turso.py
git commit -m "chore: estrutura base do projeto e conexão com o Turso"
```

---

### Task 2: `db.py` — schema e CRUD

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `db.conectar()` (Task 1)
- Produces:
  - `db.criar_schema(conn)`
  - `db.inserir_planta(conn, planta: dict) -> int` (retorna o id)
  - `db.obter_planta(conn, nome: str) -> dict | None`
  - `db.listar_plantas(conn) -> list[dict]`
  - `db.atualizar_score(conn, planta_id: int, novo_score: float)`
  - `db.registrar_historico_score(conn, planta_id, data, incremento_base, incremento_clima, score_final, et0, precipitacao_mm)`
  - `db.marcar_evento_calendario(conn, planta_id, evento_id)`
  - `db.limpar_evento_calendario(conn, planta_id)`
  - `db.registrar_rega(conn, planta_id, data, score_no_momento)`

  Dicionário de planta retornado por `obter_planta`/`listar_plantas` tem as chaves: `id, nome, temperatura_ideal_c, umidade_ideal_pct, florescimento, crescimento, crescimento2, poda, replantio, mudas, epoca_mudas, exposicao, cidade, score, ultima_rega, evento_calendario_id`.

- [ ] **Step 1: Escrever os testes (usando `sqlite3` em memória — mesmo dialeto do Turso, sem precisar de rede)**

`tests/test_db.py`:
```python
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
```

- [ ] **Step 2: Rodar os testes para confirmar que falham (as funções ainda não existem)**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `AttributeError: module 'db' has no attribute 'criar_schema'`

- [ ] **Step 3: Implementar o schema e o CRUD em `db.py`**

Adicione ao final de `db.py` (mantendo a `conectar()` do Task 1):

```python
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
```

- [ ] **Step 4: Rodar os testes de novo**

Run: `pytest tests/test_db.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: schema e CRUD do banco (plantas, historico_regas, historico_scores)"
```

---

### Task 3: `regras_score.py` — incremento base por atributo

**Files:**
- Create: `regras_score.py`
- Test: `tests/test_regras_score.py`

**Interfaces:**
- Produces:
  - `regras_score.nivel_umidade(umidade_pct: float) -> float` (retorna 15, 10 ou 6)
  - `regras_score.fator_planta(umidade_pct: float) -> float` (retorna 1.5, 1.0 ou 0.5 — usado depois em `clima.py`)
  - `regras_score.estacao_atual(data: datetime.date) -> str`
  - `regras_score.calcular_incremento_base(planta: dict, data: datetime.date) -> float`

- [ ] **Step 1: Escrever os testes**

`tests/test_regras_score.py`:
```python
import datetime

import regras_score


def test_nivel_umidade_alta():
    assert regras_score.nivel_umidade(70) == 15
    assert regras_score.nivel_umidade(65) == 15


def test_nivel_umidade_media():
    assert regras_score.nivel_umidade(60) == 10
    assert regras_score.nivel_umidade(45) == 10


def test_nivel_umidade_baixa():
    assert regras_score.nivel_umidade(40) == 6
    assert regras_score.nivel_umidade(0) == 6


def test_fator_planta_correlaciona_com_nivel_umidade():
    assert regras_score.fator_planta(70) == 1.5
    assert regras_score.fator_planta(50) == 1.0
    assert regras_score.fator_planta(30) == 0.5


def test_estacao_atual():
    assert regras_score.estacao_atual(datetime.date(2026, 1, 15)) == "Verão"
    assert regras_score.estacao_atual(datetime.date(2026, 4, 1)) == "Outono"
    assert regras_score.estacao_atual(datetime.date(2026, 7, 1)) == "Inverno"
    assert regras_score.estacao_atual(datetime.date(2026, 10, 1)) == "Primavera"


def test_incremento_base_so_umidade():
    planta = {"umidade_ideal_pct": 60, "crescimento": None, "crescimento2": None, "florescimento": None}
    assert regras_score.calcular_incremento_base(planta, datetime.date(2026, 8, 18)) == 10


def test_incremento_base_com_crescimento_ativo():
    # agosto = Inverno
    planta = {"umidade_ideal_pct": 60, "crescimento": "Inverno", "crescimento2": None, "florescimento": None}
    assert regras_score.calcular_incremento_base(planta, datetime.date(2026, 8, 18)) == 15


def test_incremento_base_com_todas_as_epocas_batendo():
    planta = {"umidade_ideal_pct": 70, "crescimento": "Inverno", "crescimento2": "Inverno", "florescimento": "Inverno"}
    # 15 (umidade) + 5 (crescimento) + 5 (crescimento2) + 3 (florescimento)
    assert regras_score.calcular_incremento_base(planta, datetime.date(2026, 8, 18)) == 28
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_regras_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'regras_score'`

- [ ] **Step 3: Implementar `regras_score.py`**

```python
"""Regras que definem quanto cada atributo da planta soma ao score por dia."""

NIVEIS_UMIDADE = [
    (65, float("inf"), 15),
    (45, 64.999, 10),
    (0, 44.999, 6),
]

FATOR_POR_NIVEL = {15: 1.5, 10: 1.0, 6: 0.5}

ESTACOES_POR_MES = {
    1: "Verão", 2: "Verão", 3: "Outono", 4: "Outono", 5: "Outono",
    6: "Inverno", 7: "Inverno", 8: "Inverno", 9: "Primavera",
    10: "Primavera", 11: "Primavera", 12: "Verão",
}


def nivel_umidade(umidade_pct):
    for minimo, maximo, valor in NIVEIS_UMIDADE:
        if minimo <= umidade_pct <= maximo:
            return valor
    raise ValueError(f"umidade fora do intervalo esperado: {umidade_pct}")


def fator_planta(umidade_pct):
    return FATOR_POR_NIVEL[nivel_umidade(umidade_pct)]


def estacao_atual(data):
    return ESTACOES_POR_MES[data.month]


def calcular_incremento_base(planta, data):
    incremento = nivel_umidade(planta["umidade_ideal_pct"])
    estacao = estacao_atual(data)
    if planta.get("crescimento") == estacao:
        incremento += 5
    if planta.get("crescimento2") == estacao:
        incremento += 5
    if planta.get("florescimento") == estacao:
        incremento += 3
    return incremento
```

- [ ] **Step 4: Rodar os testes de novo**

Run: `pytest tests/test_regras_score.py -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Commit**

```bash
git add regras_score.py tests/test_regras_score.py
git commit -m "feat: motor de regras de score por atributo"
```

---

### Task 4: `clima.py` — Open-Meteo e modificador climático

**Files:**
- Create: `clima.py`
- Test: `tests/test_clima.py`

**Interfaces:**
- Consumes: `regras_score.fator_planta` (Task 3)
- Produces:
  - `clima.buscar_dados_climaticos(lat, lon) -> dict` (JSON cru da API)
  - `clima.clima_do_dia(resposta_api: dict, data_iso: str) -> dict` com chaves `et0, precipitacao_mm, probabilidade_chuva_pct, windspeed_10m_max, uv_index_max, umidade_relativa_pct, nebulosidade_pct`
  - `clima.calcular_incremento_clima(planta: dict, clima_hoje: dict) -> float`
  - `clima.deve_adiar_aviso(score_projetado: float, clima_hoje: dict) -> bool`

- [ ] **Step 1: Escrever os testes**

`tests/test_clima.py`:
```python
from unittest.mock import Mock, patch

import clima

RESPOSTA_API_EXEMPLO = {
    "daily": {
        "time": ["2026-08-17", "2026-08-18", "2026-08-19"],
        "et0_fao_evapotranspiration": [3.0, 4.0, 3.5],
        "precipitation_sum": [0.0, 0.0, 2.0],
        "precipitation_probability_max": [10, 20, 70],
        "windspeed_10m_max": [10.0, 25.0, 12.0],
        "uv_index_max": [5.0, 9.0, 6.0],
        "relative_humidity_2m_mean": [55.0, 35.0, 60.0],
        "cloudcover_mean": [20.0, 10.0, 80.0],
    }
}


def test_clima_do_dia_encontra_a_data_certa():
    dia = clima.clima_do_dia(RESPOSTA_API_EXEMPLO, "2026-08-18")

    assert dia["et0"] == 4.0
    assert dia["precipitacao_mm"] == 0.0
    assert dia["probabilidade_chuva_pct"] == 20
    assert dia["windspeed_10m_max"] == 25.0
    assert dia["uv_index_max"] == 9.0
    assert dia["umidade_relativa_pct"] == 35.0
    assert dia["nebulosidade_pct"] == 10.0


@patch("clima.requests.get")
def test_buscar_dados_climaticos_faz_request_correto(mock_get):
    mock_resposta = Mock()
    mock_resposta.json.return_value = RESPOSTA_API_EXEMPLO
    mock_resposta.raise_for_status.return_value = None
    mock_get.return_value = mock_resposta

    resultado = clima.buscar_dados_climaticos(-23.5, -46.6)

    assert resultado == RESPOSTA_API_EXEMPLO
    args, kwargs = mock_get.call_args
    assert kwargs["params"]["latitude"] == -23.5
    assert kwargs["params"]["longitude"] == -46.6


def _clima_seco_e_quente():
    return {
        "et0": 5.0, "precipitacao_mm": 0.0, "probabilidade_chuva_pct": 5,
        "windspeed_10m_max": 25.0, "uv_index_max": 9.0,
        "umidade_relativa_pct": 30.0, "nebulosidade_pct": 10.0,
    }


def test_incremento_clima_planta_totalmente_exposta_dia_seco_aumenta_score():
    planta = {"umidade_ideal_pct": 70, "exposicao": 10}
    incremento = clima.calcular_incremento_clima(planta, _clima_seco_e_quente())
    assert incremento > 0


def test_incremento_clima_planta_dentro_de_casa_sente_bem_menos_o_sol():
    planta_exposta = {"umidade_ideal_pct": 70, "exposicao": 10}
    planta_indoor = {"umidade_ideal_pct": 70, "exposicao": 0}

    incremento_exposta = clima.calcular_incremento_clima(planta_exposta, _clima_seco_e_quente())
    incremento_indoor = clima.calcular_incremento_clima(planta_indoor, _clima_seco_e_quente())

    assert incremento_indoor < incremento_exposta


def test_incremento_clima_planta_que_precisa_de_pouca_agua_sofre_menos_com_sol():
    planta_precisa_muita_agua = {"umidade_ideal_pct": 70, "exposicao": 10}
    planta_precisa_pouca_agua = {"umidade_ideal_pct": 30, "exposicao": 10}

    incremento_alta = clima.calcular_incremento_clima(planta_precisa_muita_agua, _clima_seco_e_quente())
    incremento_baixa = clima.calcular_incremento_clima(planta_precisa_pouca_agua, _clima_seco_e_quente())

    assert incremento_baixa < incremento_alta


def test_chuva_forte_reduz_score_de_planta_exposta():
    planta = {"umidade_ideal_pct": 60, "exposicao": 10}
    clima_com_chuva = {
        "et0": 3.0, "precipitacao_mm": 10.0, "probabilidade_chuva_pct": 90,
        "windspeed_10m_max": 10.0, "uv_index_max": 3.0,
        "umidade_relativa_pct": 80.0, "nebulosidade_pct": 90.0,
    }
    incremento = clima.calcular_incremento_clima(planta, clima_com_chuva)
    assert incremento < 0


def test_chuva_nao_afeta_diretamente_planta_dentro_de_casa():
    planta = {"umidade_ideal_pct": 60, "exposicao": 0}
    clima_com_chuva = {
        "et0": 3.0, "precipitacao_mm": 10.0, "probabilidade_chuva_pct": 90,
        "windspeed_10m_max": 10.0, "uv_index_max": 3.0,
        "umidade_relativa_pct": 80.0, "nebulosidade_pct": 90.0,
    }
    incremento = clima.calcular_incremento_clima(planta, clima_com_chuva)
    # não pode zerar/reduzir drasticamente como aconteceria numa planta exposta
    assert incremento > -3


def test_deve_adiar_aviso_quando_score_alto_e_chuva_provavel():
    clima_hoje = {"probabilidade_chuva_pct": 80}
    assert clima.deve_adiar_aviso(95, clima_hoje) is True


def test_nao_deve_adiar_aviso_quando_score_baixo():
    clima_hoje = {"probabilidade_chuva_pct": 80}
    assert clima.deve_adiar_aviso(50, clima_hoje) is False


def test_nao_deve_adiar_aviso_quando_chuva_improvavel():
    clima_hoje = {"probabilidade_chuva_pct": 10}
    assert clima.deve_adiar_aviso(95, clima_hoje) is False
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_clima.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clima'`

- [ ] **Step 3: Implementar `clima.py`**

```python
"""Integração com a API gratuita do Open-Meteo e cálculo do modificador climático."""
import requests

import regras_score

VARIAVEIS_DIARIAS = [
    "et0_fao_evapotranspiration",
    "precipitation_sum",
    "precipitation_probability_max",
    "windspeed_10m_max",
    "uv_index_max",
    "relative_humidity_2m_mean",
    "cloudcover_mean",
]

LIMIAR_VENTO_KMH = 20
LIMIAR_UV_ALTO = 8
LIMIAR_UMIDADE_BAIXA = 40
LIMIAR_UMIDADE_ALTA = 80
LIMIAR_NEBULOSIDADE_ALTA = 70
FATOR_CHUVA = 5
PROBABILIDADE_CHUVA_ADIA = 60
SCORE_PROJETADO_ADIA = 90


def geocode_cidade(cidade):
    resp = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": cidade, "count": 1, "language": "pt"},
        timeout=10,
    )
    resp.raise_for_status()
    resultados = resp.json().get("results")
    if not resultados:
        raise ValueError(f"Não encontrei coordenadas para a cidade '{cidade}'.")
    return resultados[0]["latitude"], resultados[0]["longitude"]


def buscar_dados_climaticos(lat, lon, dias_passados=1, dias_futuros=2):
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(VARIAVEIS_DIARIAS),
            "timezone": "auto",
            "past_days": dias_passados,
            "forecast_days": dias_futuros,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def clima_do_dia(resposta_api, data_iso):
    diario = resposta_api["daily"]
    idx = diario["time"].index(data_iso)
    return {
        "et0": diario["et0_fao_evapotranspiration"][idx],
        "precipitacao_mm": diario["precipitation_sum"][idx] or 0.0,
        "probabilidade_chuva_pct": diario["precipitation_probability_max"][idx] or 0,
        "windspeed_10m_max": diario["windspeed_10m_max"][idx] or 0.0,
        "uv_index_max": diario["uv_index_max"][idx] or 0.0,
        "umidade_relativa_pct": diario["relative_humidity_2m_mean"][idx],
        "nebulosidade_pct": diario["cloudcover_mean"][idx],
    }


def calcular_incremento_clima(planta, clima_hoje):
    exposicao_fator = planta["exposicao"] / 10
    fator = regras_score.fator_planta(planta["umidade_ideal_pct"])

    secagem = clima_hoje["et0"] * fator * exposicao_fator

    if exposicao_fator > 0:
        if clima_hoje["windspeed_10m_max"] >= LIMIAR_VENTO_KMH:
            secagem *= 1.15
        if clima_hoje["uv_index_max"] >= LIMIAR_UV_ALTO:
            secagem *= 1.15

    if clima_hoje["umidade_relativa_pct"] < LIMIAR_UMIDADE_BAIXA:
        secagem *= 1.10
    elif clima_hoje["umidade_relativa_pct"] > LIMIAR_UMIDADE_ALTA:
        secagem *= 0.90

    if clima_hoje["nebulosidade_pct"] > LIMIAR_NEBULOSIDADE_ALTA and clima_hoje["precipitacao_mm"] == 0:
        secagem *= 0.90

    if exposicao_fator == 0:
        # dentro de casa: chuva não molha a planta, só um alívio pequeno de umidade do ar
        efeito_chuva = min(3.0, clima_hoje["precipitacao_mm"] * 0.5)
    else:
        efeito_chuva = clima_hoje["precipitacao_mm"] * FATOR_CHUVA * exposicao_fator

    return secagem - efeito_chuva


def deve_adiar_aviso(score_projetado, clima_hoje):
    return (
        score_projetado >= SCORE_PROJETADO_ADIA
        and clima_hoje["probabilidade_chuva_pct"] >= PROBABILIDADE_CHUVA_ADIA
    )
```

- [ ] **Step 4: Rodar os testes de novo**

Run: `pytest tests/test_clima.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add clima.py tests/test_clima.py
git commit -m "feat: integracao com Open-Meteo e modificador climatico completo"
```

---

### Task 5: `config.py` — cidade, coordenadas e cache

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `clima.geocode_cidade` (Task 4)
- Produces: `config.resolver_coordenadas(cidade: str, cache_path: Path = ...) -> tuple[float, float]`

- [ ] **Step 1: Escrever o teste**

`tests/test_config.py`:
```python
import json
from unittest.mock import patch

import config


def test_resolver_coordenadas_usa_cache_quando_disponivel(tmp_path):
    cache_path = tmp_path / "cidade_cache.json"
    cache_path.write_text(json.dumps({"Sao Paulo, SP": {"lat": -23.55, "lon": -46.63}}))

    with patch("config.clima.geocode_cidade") as mock_geocode:
        lat, lon = config.resolver_coordenadas("Sao Paulo, SP", cache_path=cache_path)

    assert (lat, lon) == (-23.55, -46.63)
    mock_geocode.assert_not_called()


def test_resolver_coordenadas_busca_e_grava_cache_quando_ausente(tmp_path):
    cache_path = tmp_path / "cidade_cache.json"

    with patch("config.clima.geocode_cidade", return_value=(-22.9, -43.2)) as mock_geocode:
        lat, lon = config.resolver_coordenadas("Rio de Janeiro, RJ", cache_path=cache_path)

    assert (lat, lon) == (-22.9, -43.2)
    mock_geocode.assert_called_once_with("Rio de Janeiro, RJ")

    cache_salvo = json.loads(cache_path.read_text())
    assert cache_salvo["Rio de Janeiro, RJ"] == {"lat": -22.9, "lon": -43.2}
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Implementar `config.py`**

```python
"""Configuração da cidade padrão e cache de coordenadas."""
import json
from pathlib import Path

import clima

CACHE_PADRAO = Path(__file__).parent / "cidade_cache.json"


def resolver_coordenadas(cidade, cache_path=CACHE_PADRAO):
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())

    if cidade in cache:
        return cache[cidade]["lat"], cache[cidade]["lon"]

    lat, lon = clima.geocode_cidade(cidade)
    cache[cidade] = {"lat": lat, "lon": lon}
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    return lat, lon
```

- [ ] **Step 4: Rodar o teste de novo**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: resolucao e cache de coordenadas por cidade"
```

---

### Task 6: `motor.py` — ciclo diário completo

**Files:**
- Create: `motor.py`
- Test: `tests/test_motor.py`

**Interfaces:**
- Consumes: `db.*` (Task 2), `regras_score.calcular_incremento_base` (Task 3), `clima.buscar_dados_climaticos/clima_do_dia/calcular_incremento_clima/deve_adiar_aviso` (Task 4), `config.resolver_coordenadas` (Task 5)
- Produces: `motor.rodar_ciclo(conn, hoje: datetime.date = None) -> dict` com chaves `novos_avisos`, `ainda_atrasadas`, `atualizadas` (cada uma lista de dicts)

- [ ] **Step 1: Escrever o teste (com `clima` e `config` mockados — não bate na API real)**

`tests/test_motor.py`:
```python
import datetime
import sqlite3
from unittest.mock import patch

import db
import motor

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
    "cidade": "Sao Paulo, SP",
}

CLIMA_NEUTRO = {
    "et0": 2.0, "precipitacao_mm": 0.0, "probabilidade_chuva_pct": 10,
    "windspeed_10m_max": 5.0, "uv_index_max": 3.0,
    "umidade_relativa_pct": 55.0, "nebulosidade_pct": 30.0,
}


def _conexao_teste():
    conn = sqlite3.connect(":memory:")
    db.criar_schema(conn)
    return conn


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_atualiza_score_e_grava_historico(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    db.inserir_planta(conn, PLANTA_EXEMPLO)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    planta = db.obter_planta(conn, "Jiboia")
    assert planta["score"] > 0
    assert resumo["atualizadas"][0]["nome"] == "Jiboia"

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM historico_scores")
    assert cur.fetchall()[0][0] == 1


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_gera_novo_aviso_quando_cruza_100(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["novos_avisos"]) == 1
    assert resumo["novos_avisos"][0]["nome"] == "Jiboia"
    assert resumo["ainda_atrasadas"] == []


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_nao_duplica_aviso_se_ja_tem_evento(mock_clima_dia, mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 120)
    db.marcar_evento_calendario(conn, planta_id, "evento-existente")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert resumo["novos_avisos"] == []
    assert len(resumo["ainda_atrasadas"]) == 1
    assert resumo["ainda_atrasadas"][0]["evento_calendario_id"] == "evento-existente"
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_motor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'motor'`

- [ ] **Step 3: Implementar `motor.py`**

```python
"""Roda o ciclo diário: recalcula o score de cada planta e decide quem avisar."""
import datetime

import clima
import config
import db
import regras_score


def rodar_ciclo(conn, hoje=None):
    hoje = hoje or datetime.date.today()
    coordenadas_por_cidade = {}
    resumo = {"novos_avisos": [], "ainda_atrasadas": [], "atualizadas": []}

    for planta in db.listar_plantas(conn):
        cidade = planta["cidade"]
        if cidade not in coordenadas_por_cidade:
            coordenadas_por_cidade[cidade] = config.resolver_coordenadas(cidade)
        lat, lon = coordenadas_por_cidade[cidade]

        resposta = clima.buscar_dados_climaticos(lat, lon)
        clima_hoje = clima.clima_do_dia(resposta, hoje.isoformat())

        incremento_base = regras_score.calcular_incremento_base(planta, hoje)
        incremento_clima = clima.calcular_incremento_clima(planta, clima_hoje)
        score_projetado = planta["score"] + incremento_base + incremento_clima

        adiar = clima.deve_adiar_aviso(score_projetado, clima_hoje)
        novo_score = planta["score"] if adiar else score_projetado

        db.registrar_historico_score(
            conn, planta["id"], hoje.isoformat(),
            incremento_base, incremento_clima, novo_score,
            clima_hoje["et0"], clima_hoje["precipitacao_mm"],
        )
        db.atualizar_score(conn, planta["id"], novo_score)
        resumo["atualizadas"].append({"nome": planta["nome"], "score": novo_score})

        if novo_score >= 100:
            if planta["evento_calendario_id"]:
                resumo["ainda_atrasadas"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "evento_calendario_id": planta["evento_calendario_id"],
                })
            else:
                resumo["novos_avisos"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "planta_id": planta["id"],
                })

    return resumo
```

- [ ] **Step 4: Rodar os testes de novo**

Run: `pytest tests/test_motor.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add motor.py tests/test_motor.py
git commit -m "feat: ciclo diario do motor de score"
```

---

### Task 7: `regar.py` — confirmar rega

**Files:**
- Create: `regar.py`
- Test: `tests/test_regar.py`

**Interfaces:**
- Consumes: `db.*` (Task 2)
- Produces: `regar.regar(conn, nome_planta: str, hoje: datetime.date = None) -> dict` com chaves `nome, score_anterior, evento_calendario_id_removido`

- [ ] **Step 1: Escrever os testes**

`tests/test_regar.py`:
```python
import datetime
import sqlite3

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
    }

    cur = conn.cursor()
    cur.execute("SELECT score_no_momento FROM historico_regas WHERE planta_id = ?", (planta_id,))
    assert cur.fetchall()[0][0] == 135


def test_regar_planta_inexistente_gera_erro():
    conn = _conexao_teste()
    with pytest.raises(ValueError):
        regar.regar(conn, "Não existe")
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_regar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'regar'`

- [ ] **Step 3: Implementar `regar.py`**

```python
"""Marca uma planta como regada: zera o score e limpa o lembrete pendente."""
import datetime
import json
import sys

import db


def regar(conn, nome_planta, hoje=None):
    hoje = hoje or datetime.date.today()
    planta = db.obter_planta(conn, nome_planta)
    if planta is None:
        raise ValueError(f"Planta '{nome_planta}' não encontrada.")

    evento_anterior = planta["evento_calendario_id"]
    score_anterior = planta["score"]

    db.registrar_rega(conn, planta["id"], hoje.isoformat(), score_anterior)
    db.atualizar_score(conn, planta["id"], 0)
    db.limpar_evento_calendario(conn, planta["id"])

    return {
        "nome": nome_planta,
        "score_anterior": score_anterior,
        "evento_calendario_id_removido": evento_anterior,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Uso: python3 regar.py "Nome da planta"')
        sys.exit(1)

    conexao = db.conectar()
    resultado = regar(conexao, sys.argv[1])
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Rodar os testes de novo**

Run: `pytest tests/test_regar.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Commit**

```bash
git add regar.py tests/test_regar.py
git commit -m "feat: funcao regar() para confirmar rega"
```

---

### Task 8: `migracao.py` — importar dados do notebook + corrigir o bug do `Estações`

**Files:**
- Create: `migracao.py`
- Test: `tests/test_migracao.py`
- Test fixture: `tests/fixtures/Bd_Plantas_exemplo.ipynb`

**Interfaces:**
- Consumes: `db.criar_schema`, `db.inserir_planta` (Task 2)
- Produces:
  - `migracao.carregar_dados_do_notebook(caminho_ipynb: str) -> tuple[dict, dict]` (retorna `plantas, estacoes`)
  - `migracao.migrar(conn, caminho_ipynb: str, cidade_padrao: str, exposicao_padrao: int = 5) -> list[str]`

- [ ] **Step 1: Criar a fixture de teste (uma cópia reduzida e já sem o bug de sintaxe original, pra isolar o teste do parsing do bug em si)**

`tests/fixtures/Bd_Plantas_exemplo.ipynb`:
```json
{
  "cells": [
    {
      "cell_type": "code",
      "source": [
        "plantas = {\n",
        "    'Jiboia': {\n",
        "        'Temperatura_ideal': '24°C',\n",
        "        'Umidade_ideal': '60%',\n",
        "        'Florecimento': 'Raro',\n",
        "        'Crescimento': 'Primavera',\n",
        "        'Crescimento2': 'Verão',\n",
        "        'Poda': 'Controle de tamanho',\n",
        "        'Replantio': 'Primavera',\n",
        "        'Mudas': 'Estacas em água',\n",
        "        'epoca_mudas': 'Primavera',\n",
        "        'ultima_Rega' : '21/02/2026',\n",
        "        'proxima_Rega' : '',\n",
        "    },\n",
        "}\n",
        "\n",
        "Estações{\n",
        "        'janeiro' : 'Verão',\n",
        "        'dezembro' : 'Verão',\n",
        "}"
      ]
    }
  ]
}
```

- [ ] **Step 2: Escrever os testes**

`tests/test_migracao.py`:
```python
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
```

- [ ] **Step 3: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_migracao.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migracao'`

- [ ] **Step 4: Implementar `migracao.py`**

```python
"""Migra os dados do Bd_Plantas.ipynb (dict Python) para o banco Turso,
corrigindo o bug de sintaxe do dict `Estações` (faltava o `=`)."""
import json
import sys

import db


def carregar_dados_do_notebook(caminho_ipynb):
    with open(caminho_ipynb, encoding="utf-8") as arquivo:
        notebook = json.load(arquivo)

    codigo = "".join(notebook["cells"][0]["source"])
    codigo_corrigido = codigo.replace("Estações{", "Estacoes = {", 1)

    namespace = {}
    exec(codigo_corrigido, {}, namespace)  # noqa: S102 - dict literal do próprio usuário, sem input externo

    return namespace["plantas"], namespace["Estacoes"]


def _parse_temperatura(valor):
    return float(valor.replace("°C", "").strip())


def _parse_umidade(valor):
    return float(valor.replace("%", "").strip())


def migrar(conn, caminho_ipynb, cidade_padrao, exposicao_padrao=5):
    plantas, _estacoes = carregar_dados_do_notebook(caminho_ipynb)

    inseridas = []
    for nome, atributos in plantas.items():
        planta = {
            "nome": nome,
            "temperatura_ideal_c": _parse_temperatura(atributos["Temperatura_ideal"]),
            "umidade_ideal_pct": _parse_umidade(atributos["Umidade_ideal"]),
            "florescimento": atributos.get("Florecimento"),
            "crescimento": atributos.get("Crescimento"),
            "crescimento2": atributos.get("Crescimento2"),
            "poda": atributos.get("Poda"),
            "replantio": atributos.get("Replantio"),
            "mudas": atributos.get("Mudas"),
            "epoca_mudas": atributos.get("epoca_mudas"),
            "exposicao": exposicao_padrao,
            "cidade": cidade_padrao,
        }
        db.inserir_planta(conn, planta)
        inseridas.append(nome)

    return inseridas


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 migracao.py <caminho_do_notebook.ipynb> <cidade>")
        sys.exit(1)

    caminho, cidade = sys.argv[1], sys.argv[2]
    conexao = db.conectar()
    db.criar_schema(conexao)
    resultado = migrar(conexao, caminho, cidade)
    print(f"{len(resultado)} plantas migradas: {', '.join(resultado)}")
```

- [ ] **Step 5: Rodar os testes de novo**

Run: `pytest tests/test_migracao.py -v`
Expected: PASS (2 testes)

- [ ] **Step 6: Commit**

```bash
git add migracao.py tests/test_migracao.py tests/fixtures/Bd_Plantas_exemplo.ipynb
git commit -m "feat: script de migracao do notebook para o Turso"
```

---

### Task 9: `main.py` — ponto de entrada da automação diária

**Files:**
- Create: `main.py`

**Interfaces:**
- Consumes: `db.conectar` (Task 1/2), `motor.rodar_ciclo` (Task 6)
- Produces: script executável que imprime o resumo do dia em JSON no stdout

- [ ] **Step 1: Implementar `main.py`**

```python
"""Ponto de entrada da tarefa agendada: roda o ciclo diário e imprime o
resumo em JSON para o agente ler e decidir o que avisar/agendar no
Google Calendar."""
import json

import db
import motor


def main():
    conn = db.conectar()
    db.criar_schema(conn)
    resumo = motor.rodar_ciclo(conn)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Testar manualmente (precisa do `.env` preenchido e de pelo menos uma planta migrada — feito no Task 11)**

Run: `python3 main.py`
Expected: imprime um JSON com `novos_avisos`, `ainda_atrasadas` e `atualizadas` sem lançar exceção.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: ponto de entrada da automacao diaria"
```

---

### Task 10: Publicar o repositório no GitHub

A tarefa agendada roda numa sessão nova todo dia — ela precisa buscar o código de algum lugar acessível pela internet (não pode depender do seu PC estar ligado). Vamos publicar num repositório GitHub.

**Files:** nenhum arquivo novo — só configuração de repositório remoto.

- [ ] **Step 1: Criar o repositório**

1. Acesse https://github.com/new (crie uma conta gratuita se ainda não tiver).
2. Crie um repositório **público** chamado `calculadora-rega` (público é mais simples — não vai ter nenhuma credencial no código, elas ficam só em variáveis de ambiente).
3. Não inicialize com README/gitignore (o projeto já tem os arquivos).

- [ ] **Step 2: Gerar um token de acesso pessoal (Personal Access Token)**

Em https://github.com/settings/tokens, gere um token com permissão `repo` (só pra dar `git push`). Guarde o valor.

- [ ] **Step 3: Conectar o repositório local ao remoto e enviar o código**

```bash
cd /home/claude/calculadora-rega
git remote add origin https://github.com/<seu-usuario>/calculadora-rega.git
git branch -M main
git push -u origin main
```

Quando pedir usuário/senha, use seu usuário do GitHub e o token gerado no Step 2 como senha.

- [ ] **Step 4: Confirmar**

Run: `git remote -v`
Expected: mostra `origin` apontando para o repositório do GitHub.

Acesse a página do repositório no navegador e confirme que os arquivos estão lá (menos `.env`, que fica de fora por causa do `.gitignore`).

---

### Task 11: Migrar os dados reais e corrigir o notebook local

**Files:**
- Modify (no PC do usuário, via device bridge): `Bd_Plantas.ipynb`

- [ ] **Step 1: Copiar o notebook real do PC do usuário para o container**

Usar `device_stage_files` com o caminho `C:\Users\triol\Desktop\Projeto\Calculadora de rega de planta\Bd_Plantas.ipynb` (já foi feito uma vez nesta sessão; repetir se o arquivo mudou).

- [ ] **Step 2: Rodar a migração real**

Run: `python3 migracao.py "/mnt/user-data/uploads/Calculadora de rega de planta/Bd_Plantas.ipynb" "<cidade do usuário>"`
Expected: imprime `8 plantas migradas: ...` (as 8 plantas do notebook original).

- [ ] **Step 3: Conferir no banco**

Run: `python3 -c "import db; conn = db.conectar(); print([p['nome'] for p in db.listar_plantas(conn)])"`
Expected: lista com as 8 plantas.

- [ ] **Step 4: Ajustar a exposição de cada planta (o padrão da migração é 5 para todas)**

Primeiro adicionar um helper em `db.py` (mesmo padrão de `atualizar_score`):

```python
def atualizar_exposicao(conn, planta_id, nova_exposicao):
    cur = conn.cursor()
    cur.execute("UPDATE plantas SET exposicao = ? WHERE id = ?", (nova_exposicao, planta_id))
    conn.commit()
```

Teste rápido em `tests/test_db.py` (mesmo padrão de `test_atualizar_score`):

```python
def test_atualizar_exposicao():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)

    db.atualizar_exposicao(conn, planta_id, 10)

    assert db.obter_planta(conn, "Jiboia")["exposicao"] == 10
```

Run: `pytest tests/test_db.py -v` — Expected: PASS (8 testes agora).

```bash
git add db.py tests/test_db.py
git commit -m "feat: helper para ajustar exposicao de uma planta"
```

Depois, perguntar ao usuário a exposição real (0, 5 ou 10) de cada uma das 8 plantas e rodar, para cada uma:

```bash
python3 -c "
import db
conn = db.conectar()
planta = db.obter_planta(conn, 'Jiboia')
db.atualizar_exposicao(conn, planta['id'], 5)
"
```

(repetir trocando o nome da planta e o valor de exposição.)

- [ ] **Step 5: Corrigir o bug de sintaxe no notebook original do usuário**

```python
caminho = "/tmp/Bd_Plantas_corrigido.ipynb"
import json
with open("/mnt/user-data/uploads/Calculadora de rega de planta/Bd_Plantas.ipynb", encoding="utf-8") as f:
    nb = json.load(f)
codigo = nb["cells"][0]["source"]
nb["cells"][0]["source"] = [linha.replace("Estações{", "Estações = {") for linha in codigo]
with open(caminho, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
```

Depois enviar com `SendUserFile` e gravar de volta no PC do usuário com `device_commit_files` (mesmo caminho original), avisando que o notebook agora é só consulta — o banco manda.

---

### Task 12: Criar a tarefa agendada

**Files:** nenhum arquivo de código — configuração via `create_trigger`.

- [ ] **Step 1: Montar o prompt da tarefa agendada**

O prompt (texto que a tarefa agendada vai executar todo dia, numa sessão nova) precisa:

1. Clonar/atualizar o repositório: `git clone https://github.com/<usuario>/calculadora-rega.git` (ou `git pull` se já existir).
2. Instalar dependências: `pip install -r requirements.txt --break-system-packages`.
3. Exportar as variáveis de ambiente com os valores reais do Turso (`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `CIDADE_PADRAO`).
4. Rodar `python3 main.py` e ler o JSON impresso.
5. Para cada planta em `novos_avisos`: criar um evento no Google Calendar do usuário ("💧 Regar: <nome>", hoje, descrição com o score) usando as ferramentas `mcp__Google_Calendar__create_event`; guardar o id retornado chamando `db.marcar_evento_calendario` (pode ser via um pequeno script Python inline ou um comando `python3 -c`).
6. Para cada planta em `ainda_atrasadas`: opcionalmente atualizar a descrição do evento existente via `mcp__Google_Calendar__update_event` com o novo score.
7. Enviar um resumo por push/e-mail (usa a notificação nativa da tarefa agendada) listando as plantas que precisam de água.

- [ ] **Step 2: Criar a tarefa com `create_trigger`**

Chamar `create_trigger` com:
- `name`: "Calculadora de rega — ciclo diário"
- `cron_expression`: horário escolhido pelo usuário (ex: `0 11 * * *` para 08:00 no horário de Brasília, já convertido pra UTC)
- `prompt`: o texto montado no Step 1, com os valores reais de URL/token do Turso e a cidade
- `notifications`: `{"push": true}` (ou `{"push": true, "email": true}`, perguntar preferência ao usuário)

- [ ] **Step 3: Testar manualmente**

Usar `fire_trigger` pra disparar a tarefa uma vez fora do horário programado e conferir se ela roda até o fim sem erro.

---

### Task 13: Verificação ponta-a-ponta

**Files:** nenhum novo — só validação manual do sistema completo.

- [ ] **Step 1: Rodar a suíte de testes completa**

Run: `pytest -v`
Expected: todos os testes de `tests/test_regras_score.py`, `tests/test_clima.py`, `tests/test_config.py`, `tests/test_db.py`, `tests/test_motor.py`, `tests/test_regar.py`, `tests/test_migracao.py` passam.

- [ ] **Step 2: Simular uma planta atrasada**

```bash
python3 -c "
import db
conn = db.conectar()
planta = db.obter_planta(conn, 'Jiboia')
db.atualizar_score(conn, planta['id'], 130)
"
python3 main.py
```

Expected: `Jiboia` aparece em `novos_avisos` no JSON impresso.

- [ ] **Step 3: Disparar a tarefa agendada manualmente (`fire_trigger`) e confirmar**

- Um evento "💧 Regar: Jiboia" aparece no Google Calendar do usuário.
- Uma notificação push chegou.

- [ ] **Step 4: Confirmar a rega e checar que o evento some**

Run: `python3 regar.py "Jiboia"`
Expected: imprime o JSON de confirmação com `score_anterior: 130`.

Disparar a tarefa agendada de novo (`fire_trigger`) e confirmar que o evento "💧 Regar: Jiboia" foi removido do Google Calendar e que `Jiboia` não aparece mais em `novos_avisos`/`ainda_atrasadas`.

- [ ] **Step 5: Entregar o projeto final ao usuário**

Enviar os arquivos principais via `SendUserFile` e, se o usuário quiser uma cópia local também, gravar em `C:\Users\triol\Desktop\Projeto\Calculadora de rega de planta\` via `device_commit_files`.
