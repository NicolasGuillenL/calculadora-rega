# Calculadora de Rega de Planta v2 — Retenção de Substrato + Agenda Proativa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar um fator de retenção de substrato ao cálculo climático e um mecanismo de projeção de 2 dias que cria/atualiza/cancela eventos "previsão" no Google Calendar do usuário, promovendo-os a eventos confirmados quando a planta de fato cruza score 100.

**Architecture:** Extensão da v1 já em produção (worktree `/home/claude/calculadora-rega-impl`, branch `implementacao-score-rega`, HEAD `ded7019`). Adiciona duas colunas à tabela `plantas` (`retencao_substrato`, `evento_projetado_id`), um multiplicador novo em `clima.calcular_incremento_clima`, uma função pura de simulação em `motor.py`, e integra os dois na automação diária existente — sem criar módulos novos nem mudar a arquitetura geral (Turso, Open-Meteo, Google Calendar via MCP na camada do agente, tarefa agendada única às 7h).

**Tech Stack:** Python 3, `libsql_experimental` (Turso), `requests` (Open-Meteo), `pytest`. Mesmo stack da v1, sem dependências novas.

**Spec:** `docs/superpowers/specs/2026-08-18-calculadora-rega-v2-design.md`

## Global Constraints

- Retenção de substrato: 3 níveis (`alta`/`media`/`baixa`), multiplicadores `alta=0.6`, `media=1.0`, `baixa=1.3`, aplicados só no termo de secagem (et0/sol/vento) — nunca no efeito da chuva medida.
- Horizonte de projeção: 2 dias à frente (não conta o dia de hoje).
- O score real da planta só reage a chuva **medida** — a previsão de chuva nunca desconta o score antecipadamente, só entra na simulação de projeção (que decide sobre o evento no Calendar, não sobre o score gravado).
- Uma única execução diária (7h) — nenhuma automação nova. Todo evento de rega (projetado ou confirmado) é criado como evento com horário marcado 17h40–18h no dia relevante, não mais "dia inteiro".
- Título distingue os dois estados: `"🌦️ Possível rega: <nome> (previsão)"` enquanto projetado, `"💧 Regar: <nome>"` quando confirmado.
- Evento projetado que se confirma vira o evento real (mesmo ID no Calendar) — nunca cancela-e-recria. Evento projetado que deixa de ser aplicável é cancelado, sem recriação automática nesse mesmo ciclo.
- O mecanismo de adiamento já existente na v1 (`deve_adiar_aviso`) continua funcionando sem alteração; se o cruzamento real de hoje é adiado, a promoção projetado→confirmado não acontece nesse ciclo.

---

## Nota sobre a janela de previsão do Open-Meteo

A spec assumia que a chamada já existente (`dias_futuros=2`) já cobria os 2 dias futuros necessários pra projeção. Na prática, o parâmetro `forecast_days` do Open-Meteo conta a partir de hoje **incluindo hoje**: `dias_futuros=2` retorna hoje + 1 dia futuro, não hoje + 2. Confirmado rodando a API de verdade:

```
dias_futuros=2: ['2026-08-17', '2026-08-18', '2026-08-19']       # só 1 dia futuro (19)
dias_futuros=3: ['2026-08-17', '2026-08-18', '2026-08-19', '2026-08-20']  # 2 dias futuros (19, 20)
```

Este plano ajusta o valor padrão de `dias_futuros` em `clima.buscar_dados_climaticos` de 2 para 3 (Task 2). Continua sendo uma única chamada por cidade por dia — só pede uma janela um pouco maior, não adiciona requests.

---

### Task 1: Schema v2 — colunas novas e migração idempotente

**Files:**
- Modify: `db.py`
- Modify: `migracao.py`
- Test: `tests/test_db.py`
- Test: `tests/test_motor.py` (só o fixture `PLANTA_EXEMPLO`, sem mudar lógica)
- Test: `tests/test_regar.py` (só o fixture `PLANTA_EXEMPLO`, sem mudar lógica)

**Interfaces:**
- Produces: `db.migrar_schema_v2(conn) -> None` (idempotente); coluna `retencao_substrato TEXT NOT NULL DEFAULT 'media'` e `evento_projetado_id TEXT` na tabela `plantas`; `CAMPOS_PLANTA` passa a incluir `"retencao_substrato"` (precisa estar no dict passado a `inserir_planta`, mesma convenção já usada para `"exposicao"`).

Por que a tabela `plantas` precisa de uma migração explícita (diferente da v1, que nunca mudou o schema depois de criado): `criar_schema` usa `CREATE TABLE IF NOT EXISTS`, que não adiciona colunas a uma tabela já existente. O banco Turso de produção já tem a tabela `plantas` populada com 7 linhas — só recriar o `CREATE TABLE` no código não basta.

- [ ] **Step 1: Escrever o teste que falha pra `migrar_schema_v2`**

Adicionar em `tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python3 -m pytest tests/test_db.py::test_migrar_schema_v2_adiciona_colunas_novas -v`
Expected: FAIL com `AttributeError: module 'db' has no attribute 'migrar_schema_v2'`

- [ ] **Step 3: Implementar `migrar_schema_v2` e atualizar o `SCHEMA`**

Em `db.py`, atualizar a definição de `SCHEMA` (só a tabela `plantas` muda; `historico_regas` e `historico_scores` continuam iguais):

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
"""

CAMPOS_PLANTA = [
    "nome", "temperatura_ideal_c", "umidade_ideal_pct", "florescimento",
    "crescimento", "crescimento2", "poda", "replantio", "mudas",
    "epoca_mudas", "exposicao", "cidade", "retencao_substrato",
]
```

Adicionar a função de migração (pode ficar logo depois de `criar_schema`):

```python
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
```

E atualizar `criar_schema` pra sempre chamar a migração depois de criar as tabelas (assim qualquer código que já chama `db.criar_schema(conn)` — incluindo a tarefa agendada, que roda isso todo dia — mantém o schema em dia sozinho, sem precisar de um passo manual separado):

```python
def criar_schema(conn):
    cur = conn.cursor()
    for instrucao in SCHEMA.strip().split(";"):
        instrucao = instrucao.strip()
        if instrucao:
            cur.execute(instrucao)
    conn.commit()
    migrar_schema_v2(conn)
```

Por fim, mudar `inserir_planta` pra usar a nova lista de `CAMPOS_PLANTA` — o corpo da função **não muda**, só o fato de `CAMPOS_PLANTA` agora ter um item a mais já faz `inserir_planta` exigir `"retencao_substrato"` no dict `planta` (mesma convenção de `"exposicao"`, que já é obrigatório hoje).

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python3 -m pytest tests/test_db.py::test_migrar_schema_v2_adiciona_colunas_novas -v`
Expected: PASS

- [ ] **Step 5: Corrigir os fixtures que agora quebram por falta de `retencao_substrato`**

Como `CAMPOS_PLANTA` agora inclui `"retencao_substrato"` e a coluna é `NOT NULL`, qualquer dict `PLANTA_EXEMPLO` que não tiver essa chave vai causar erro de integridade ao inserir (`planta.get("retencao_substrato")` retorna `None`, que tenta gravar `NULL` numa coluna `NOT NULL`). Adicionar `"retencao_substrato": "media",` em:

- `tests/test_db.py`, no dict `PLANTA_EXEMPLO` (logo depois de `"exposicao": 5,`)
- `tests/test_motor.py`, no dict `PLANTA_EXEMPLO` (logo depois de `"exposicao": 5,`)
- `tests/test_regar.py`, no dict `PLANTA_EXEMPLO` (logo depois de `"exposicao": 5,`)

Em `migracao.py`, adicionar um parâmetro `retencao_substrato_padrao="media"` na assinatura de `migrar` e incluir a chave no dict `planta` construído dentro do loop:

```python
def migrar(conn, caminho_ipynb, cidade_padrao, exposicao_padrao=5, retencao_substrato_padrao="media"):
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
            "retencao_substrato": retencao_substrato_padrao,
        }
        db.inserir_planta(conn, planta)
        inseridas.append(nome)

    return inseridas
```

- [ ] **Step 6: Rodar a suíte completa e confirmar que passa**

Run: `python3 -m pytest -q`
Expected: PASS (todos os 53 testes existentes + o novo)

- [ ] **Step 7: Commit**

```bash
git add db.py migracao.py tests/test_db.py tests/test_motor.py tests/test_regar.py
git commit -m "feat: colunas retencao_substrato e evento_projetado_id + migracao idempotente"
```

---

### Task 2: Fator de retenção do substrato no cálculo climático

**Files:**
- Modify: `clima.py`
- Test: `tests/test_clima.py`

**Interfaces:**
- Consumes: `planta["retencao_substrato"]` (opcional — se ausente, assume `"media"`, pra não quebrar chamadas antigas que não sabem desse campo).
- Produces: `clima.FATOR_RETENCAO` (dict), `clima.buscar_dados_climaticos` com `dias_futuros` padrão `3` (era `2`).

`calcular_incremento_clima` usa `planta.get("retencao_substrato", "media")` (não `planta["retencao_substrato"]`) — de propósito: essa função já tem uma convenção própria de defaults tolerantes (ver `clima_do_dia`, que usa `or 0.0` pros campos da API), e isso evita ter que editar os vários dicts de planta pequenos já usados nos testes existentes de `test_clima.py`. Isso é diferente da decisão da Task 1 pra `db.inserir_planta` (que exige `retencao_substrato` explícito, igual `exposicao`) — lá faz sentido exigir porque é um dado real por planta que vem de uma pergunta ao usuário; aqui é só uma função de cálculo pura, e testes antigos não precisam saber desse conceito novo.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar em `tests/test_clima.py`:

```python
def test_incremento_clima_retencao_alta_amortece_secagem():
    planta_media = {"umidade_ideal_pct": 70, "exposicao": 10, "retencao_substrato": "media"}
    planta_alta = {"umidade_ideal_pct": 70, "exposicao": 10, "retencao_substrato": "alta"}

    incremento_media = clima.calcular_incremento_clima(planta_media, _clima_seco_e_quente())
    incremento_alta = clima.calcular_incremento_clima(planta_alta, _clima_seco_e_quente())

    assert incremento_alta < incremento_media


def test_incremento_clima_retencao_baixa_acelera_secagem():
    planta_media = {"umidade_ideal_pct": 70, "exposicao": 10, "retencao_substrato": "media"}
    planta_baixa = {"umidade_ideal_pct": 70, "exposicao": 10, "retencao_substrato": "baixa"}

    incremento_media = clima.calcular_incremento_clima(planta_media, _clima_seco_e_quente())
    incremento_baixa = clima.calcular_incremento_clima(planta_baixa, _clima_seco_e_quente())

    assert incremento_baixa > incremento_media


def test_incremento_clima_sem_retencao_substrato_usa_media_por_padrao():
    planta_sem_campo = {"umidade_ideal_pct": 70, "exposicao": 10}
    planta_media_explicita = {"umidade_ideal_pct": 70, "exposicao": 10, "retencao_substrato": "media"}

    incremento_sem_campo = clima.calcular_incremento_clima(planta_sem_campo, _clima_seco_e_quente())
    incremento_media_explicita = clima.calcular_incremento_clima(planta_media_explicita, _clima_seco_e_quente())

    assert incremento_sem_campo == incremento_media_explicita


@patch("clima.requests.get")
def test_buscar_dados_climaticos_pede_3_dias_futuros_por_padrao(mock_get):
    mock_resposta = Mock()
    mock_resposta.json.return_value = RESPOSTA_API_EXEMPLO
    mock_resposta.raise_for_status.return_value = None
    mock_get.return_value = mock_resposta

    clima.buscar_dados_climaticos(-23.5, -46.6)

    args, kwargs = mock_get.call_args
    assert kwargs["params"]["forecast_days"] == 3
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python3 -m pytest tests/test_clima.py -v -k "retencao or 3_dias"`
Expected: FAIL (`KeyError: 'alta'` nos dois primeiros porque `FATOR_RETENCAO` não existe ainda; o terceiro passa "sem querer" porque hoje o resultado já é igual pra qualquer planta sem esse campo — vai continuar passando depois, não é regressão); o de `forecast_days` falha esperando `3` e recebendo `2`.

- [ ] **Step 3: Implementar**

Em `clima.py`, adicionar o dict de fatores logo junto dos outros limiares:

```python
FATOR_RETENCAO = {"alta": 0.6, "media": 1.0, "baixa": 1.3}
```

Mudar a assinatura padrão de `buscar_dados_climaticos`:

```python
def buscar_dados_climaticos(lat, lon, dias_passados=1, dias_futuros=3):
    resp = _get_com_retry(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(VARIAVEIS_DIARIAS),
            "timezone": "auto",
            "past_days": dias_passados,
            "forecast_days": dias_futuros,
        },
    )
    return resp.json()
```

E em `calcular_incremento_clima`, aplicar o multiplicador no termo de secagem:

```python
def calcular_incremento_clima(planta, clima_hoje):
    exposicao_fator = planta["exposicao"] / 10
    fator = regras_score.fator_planta(planta["umidade_ideal_pct"])
    fator_retencao = FATOR_RETENCAO[planta.get("retencao_substrato", "media")]

    secagem = clima_hoje["et0"] * fator * fator_retencao * exposicao_fator

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
        efeito_chuva = min(
            LIMIAR_ALIVIO_CHUVA_INDOOR_MAX,
            clima_hoje["precipitacao_mm"] * FATOR_ALIVIO_CHUVA_INDOOR,
        )
    else:
        efeito_chuva = clima_hoje["precipitacao_mm"] * FATOR_CHUVA * exposicao_fator

    return secagem - efeito_chuva
```

(o resto da função — cálculo de `efeito_chuva` — não muda, `fator_retencao` só entra em `secagem`.)

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python3 -m pytest tests/test_clima.py -v`
Expected: PASS (todos, incluindo os já existentes)

- [ ] **Step 5: Rodar a suíte completa**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add clima.py tests/test_clima.py
git commit -m "feat: fator de retencao de substrato no calculo de secagem"
```

---

### Task 3: `simular_projecao` — projeção pura de 2 dias

**Files:**
- Modify: `motor.py`
- Test: `tests/test_motor.py`

**Interfaces:**
- Consumes: `clima.clima_do_dia`, `clima.calcular_incremento_clima`, `regras_score.calcular_incremento_base` (já existem, sem mudança de assinatura).
- Produces: `motor.simular_projecao(planta, resposta_clima, hoje) -> str | None` — retorna a data ISO (`"YYYY-MM-DD"`) em que o score projetado cruzaria 100, considerando só os dias **depois** de `hoje` presentes em `resposta_clima["daily"]["time"]`, ou `None` se não cruza dentro dos dias disponíveis. Função pura: não grava nada no banco, não faz request de rede.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar em `tests/test_motor.py` (usa o mesmo `PLANTA_EXEMPLO` e `_conexao_teste` já existentes no arquivo):

```python
RESPOSTA_PROJECAO_CRUZA_DIA_20 = {
    "daily": {
        "time": ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"],
        "et0_fao_evapotranspiration": [999.0, 999.0, 5.0, 5.0],
        "precipitation_sum": [0.0, 0.0, 0.0, 0.0],
        "precipitation_probability_max": [10, 10, 10, 10],
        "windspeed_10m_max": [5.0, 5.0, 5.0, 5.0],
        "uv_index_max": [3.0, 3.0, 3.0, 3.0],
        "relative_humidity_2m_mean": [55.0, 55.0, 55.0, 55.0],
        "cloudcover_mean": [20.0, 20.0, 20.0, 20.0],
    }
}


def test_simular_projecao_detecta_cruzamento_em_2_dias():
    planta = {**PLANTA_EXEMPLO, "umidade_ideal_pct": 70.0, "exposicao": 10, "score": 60}

    data_prevista = motor.simular_projecao(planta, RESPOSTA_PROJECAO_CRUZA_DIA_20, datetime.date(2026, 8, 18))

    assert data_prevista == "2026-08-20"


def test_simular_projecao_ignora_dias_passados_e_hoje():
    # et0 gigante nos dias 17 e 18 (passado/hoje) não pode ser contado —
    # se fosse, cruzaria no primeiro dia. Só 19 e 20 (futuros) entram.
    planta = {**PLANTA_EXEMPLO, "umidade_ideal_pct": 70.0, "exposicao": 10, "score": 0}

    data_prevista = motor.simular_projecao(planta, RESPOSTA_PROJECAO_CRUZA_DIA_20, datetime.date(2026, 8, 18))

    # com score 0 e só os 2 dias futuros "fracos" (et0=5.0), não cruza 100
    assert data_prevista is None


def test_simular_projecao_retorna_none_quando_nao_cruza():
    resposta_fraca = {
        "daily": {
            "time": ["2026-08-18", "2026-08-19", "2026-08-20"],
            "et0_fao_evapotranspiration": [1.0, 1.0, 1.0],
            "precipitation_sum": [0.0, 0.0, 0.0],
            "precipitation_probability_max": [10, 10, 10],
            "windspeed_10m_max": [5.0, 5.0, 5.0],
            "uv_index_max": [3.0, 3.0, 3.0],
            "relative_humidity_2m_mean": [55.0, 55.0, 55.0],
            "cloudcover_mean": [20.0, 20.0, 20.0],
        }
    }
    planta = {**PLANTA_EXEMPLO, "umidade_ideal_pct": 30.0, "exposicao": 5, "score": 0}

    data_prevista = motor.simular_projecao(planta, resposta_fraca, datetime.date(2026, 8, 18))

    assert data_prevista is None
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python3 -m pytest tests/test_motor.py -v -k simular_projecao`
Expected: FAIL com `AttributeError: module 'motor' has no attribute 'simular_projecao'`

- [ ] **Step 3: Implementar**

Em `motor.py`, adicionar a função (pode ficar antes de `rodar_ciclo`):

```python
def simular_projecao(planta, resposta_clima, hoje):
    """Simula o score da planta pros dias futuros disponíveis na resposta do
    Open-Meteo, sem gravar nada em lugar nenhum — usa a mesma fórmula do
    ciclo real, incluindo a chuva PREVISTA (não medida) pros dias que ainda
    não aconteceram. Retorna a data ISO em que o score projetado cruzaria
    100, ou None se não cruza dentro dos dias disponíveis na resposta."""
    hoje_iso = hoje.isoformat()
    datas_futuras = sorted(d for d in resposta_clima["daily"]["time"] if d > hoje_iso)

    score = planta["score"]
    for data_iso in datas_futuras:
        data = datetime.date.fromisoformat(data_iso)
        clima_dia = clima.clima_do_dia(resposta_clima, data_iso)
        incremento_base = regras_score.calcular_incremento_base(planta, data)
        incremento_clima = clima.calcular_incremento_clima(planta, clima_dia)
        score = max(0.0, score + incremento_base + incremento_clima)
        if score >= 100:
            return data_iso
    return None
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python3 -m pytest tests/test_motor.py -v -k simular_projecao`
Expected: PASS

- [ ] **Step 5: Rodar a suíte completa**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add motor.py tests/test_motor.py
git commit -m "feat: simular_projecao pura pra decidir eventos futuros na agenda"
```

---

### Task 4: Helpers de evento projetado e retenção em `db.py`

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.marcar_evento_projetado(conn, planta_id, evento_id) -> None`, `db.limpar_evento_projetado(conn, planta_id) -> None`, `db.promover_evento_projetado(conn, planta_id, evento_id) -> None` (grava `evento_id` em `evento_calendario_id` e limpa `evento_projetado_id` numa única operação), `db.atualizar_retencao_substrato(conn, planta_id, novo_valor) -> None`.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar em `tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python3 -m pytest tests/test_db.py -v -k "projetado or retencao_substrato"`
Expected: FAIL com `AttributeError` pra cada função ainda não implementada.

- [ ] **Step 3: Implementar**

Em `db.py`, adicionar logo depois de `limpar_evento_calendario`:

```python
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
    cur = conn.cursor()
    cur.execute("UPDATE plantas SET retencao_substrato = ? WHERE id = ?", (novo_valor, planta_id))
    conn.commit()
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python3 -m pytest tests/test_db.py -v -k "projetado or retencao_substrato"`
Expected: PASS

- [ ] **Step 5: Rodar a suíte completa**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: helpers de evento projetado (marcar/limpar/promover) e retencao_substrato"
```

---

### Task 5: Integrar projeção e promoção no `rodar_ciclo`

**Files:**
- Modify: `motor.py`
- Test: `tests/test_motor.py`

**Interfaces:**
- Consumes: `motor.simular_projecao` (Task 3), `planta["evento_projetado_id"]` (Task 1).
- Produces: `resumo["projecoes"]` — lista de dicts `{"acao": "criar"|"atualizar"|"cancelar", "nome": str, "planta_id": int, "data_prevista": str, ...}` (`"data_prevista"` só em `"criar"`/`"atualizar"`; `"evento_projetado_id"` só em `"atualizar"`/`"cancelar"`). Entradas de `resumo["novos_avisos"]` ganham uma chave opcional `"evento_projetado_id"` quando a planta já tinha um evento projetado que precisa virar o confirmado (a camada do agente usa isso pra saber se deve chamar `promover_evento_projetado` em vez de criar um evento novo).

- [ ] **Step 1: Escrever os testes que falham**

Adicionar em `tests/test_motor.py`. **Importante:** estes testes mockam só `buscar_dados_climaticos` e `resolver_coordenadas` — **não** mockam `clima_do_dia` (diferente de outros testes do arquivo). `simular_projecao` chama `clima.clima_do_dia` internamente pra ler o et0/chuva de cada dia futuro; se `clima_do_dia` estivesse mockado pra devolver sempre o mesmo `CLIMA_NEUTRO`, os valores por dia que os testes configuram abaixo (et0 diferente em cada data) seriam ignorados e a simulação leria dado errado.

```python
RESPOSTA_PROJECAO_CICLO = {
    "daily": {
        "time": ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"],
        "et0_fao_evapotranspiration": [3.0, 1.0, 5.0, 5.0],
        "precipitation_sum": [0.0, 0.0, 0.0, 0.0],
        "precipitation_probability_max": [10, 10, 10, 10],
        "windspeed_10m_max": [5.0, 5.0, 5.0, 5.0],
        "uv_index_max": [3.0, 3.0, 3.0, 3.0],
        "relative_humidity_2m_mean": [55.0, 55.0, 55.0, 55.0],
        "cloudcover_mean": [20.0, 20.0, 20.0, 20.0],
    }
}


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value=RESPOSTA_PROJECAO_CICLO)
def test_rodar_ciclo_cria_projecao_quando_score_nao_cruza_hoje_mas_projeta_em_2_dias(
    mock_busca, mock_coords
):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, {**PLANTA_EXEMPLO, "umidade_ideal_pct": 70.0, "exposicao": 10})
    db.atualizar_score(conn, planta_id, 50)  # + hoje (et0=1.0) => novo_score ~66.5, ainda < 100

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["projecoes"]) == 1
    projecao = resumo["projecoes"][0]
    assert projecao["acao"] == "criar"
    assert projecao["nome"] == "Jiboia"
    assert projecao["data_prevista"] == "2026-08-20"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value=RESPOSTA_PROJECAO_CICLO)
def test_rodar_ciclo_atualiza_projecao_existente(mock_busca, mock_coords):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, {**PLANTA_EXEMPLO, "umidade_ideal_pct": 70.0, "exposicao": 10})
    db.atualizar_score(conn, planta_id, 50)
    db.marcar_evento_projetado(conn, planta_id, "projetado-existente")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["projecoes"]) == 1
    projecao = resumo["projecoes"][0]
    assert projecao["acao"] == "atualizar"
    assert projecao["evento_projetado_id"] == "projetado-existente"
    assert projecao["data_prevista"] == "2026-08-20"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos")
def test_rodar_ciclo_cancela_projecao_que_nao_se_confirma_mais(mock_busca, mock_coords):
    resposta_chuva_forte = {
        "daily": {
            "time": ["2026-08-18", "2026-08-19", "2026-08-20"],
            "et0_fao_evapotranspiration": [1.0, 1.0, 1.0],
            "precipitation_sum": [0.0, 20.0, 20.0],
            "precipitation_probability_max": [10, 90, 90],
            "windspeed_10m_max": [5.0, 5.0, 5.0],
            "uv_index_max": [3.0, 3.0, 3.0],
            "relative_humidity_2m_mean": [55.0, 55.0, 55.0],
            "cloudcover_mean": [20.0, 20.0, 20.0],
        }
    }
    mock_busca.return_value = resposta_chuva_forte
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, {**PLANTA_EXEMPLO, "umidade_ideal_pct": 30.0, "exposicao": 10})
    db.atualizar_score(conn, planta_id, 10)  # + hoje (sem chuva ainda) => novo_score ~16.5, < 100
    db.marcar_evento_projetado(conn, planta_id, "projetado-existente")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["projecoes"]) == 1
    projecao = resumo["projecoes"][0]
    assert projecao["acao"] == "cancelar"
    assert projecao["evento_projetado_id"] == "projetado-existente"


@patch("motor.config.resolver_coordenadas", return_value=(-23.5, -46.6))
@patch("motor.clima.buscar_dados_climaticos", return_value={"daily": {"time": ["2026-08-18"]}})
@patch("motor.clima.clima_do_dia", return_value=CLIMA_NEUTRO)
def test_rodar_ciclo_cruzamento_real_carrega_evento_projetado_pra_promover(
    mock_clima_dia, mock_busca, mock_coords
):
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.atualizar_score(conn, planta_id, 95)
    db.marcar_evento_projetado(conn, planta_id, "projetado-existente")

    resumo = motor.rodar_ciclo(conn, hoje=datetime.date(2026, 8, 18))

    assert len(resumo["novos_avisos"]) == 1
    assert resumo["novos_avisos"][0]["evento_projetado_id"] == "projetado-existente"
    assert resumo["projecoes"] == []
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python3 -m pytest tests/test_motor.py -v -k "projecao or promover"`
Expected: FAIL — `resumo["projecoes"]` não existe ainda (`KeyError`), e a entrada de `novos_avisos` não carrega `evento_projetado_id`.

- [ ] **Step 3: Implementar**

Substituir `rodar_ciclo` inteira em `motor.py` por:

```python
def rodar_ciclo(conn, hoje=None):
    hoje = hoje or datetime.date.today()
    hoje_iso = hoje.isoformat()
    coordenadas_por_cidade = {}
    clima_por_cidade = {}
    resumo = {
        "novos_avisos": [], "ainda_atrasadas": [], "atualizadas": [],
        "adiados": [], "projecoes": [],
    }

    for planta in db.listar_plantas(conn):
        if db.ja_processado_hoje(conn, planta["id"], hoje_iso):
            if planta["score"] >= 100 and planta["evento_calendario_id"]:
                resumo["ainda_atrasadas"].append({
                    "nome": planta["nome"],
                    "score": planta["score"],
                    "evento_calendario_id": planta["evento_calendario_id"],
                })
            continue

        cidade = planta["cidade"]
        if cidade not in coordenadas_por_cidade:
            coordenadas_por_cidade[cidade] = config.resolver_coordenadas(cidade)
        lat, lon = coordenadas_por_cidade[cidade]

        if cidade not in clima_por_cidade:
            clima_por_cidade[cidade] = clima.buscar_dados_climaticos(lat, lon)
        resposta = clima_por_cidade[cidade]
        clima_hoje = clima.clima_do_dia(resposta, hoje_iso)

        incremento_base = regras_score.calcular_incremento_base(planta, hoje)
        incremento_clima = clima.calcular_incremento_clima(planta, clima_hoje)
        score_projetado = planta["score"] + incremento_base + incremento_clima

        adiar = clima.deve_adiar_aviso(score_projetado, clima_hoje)
        novo_score = max(0.0, score_projetado)

        db.registrar_historico_score(
            conn, planta["id"], hoje_iso,
            incremento_base, incremento_clima, score_projetado,
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
            elif adiar:
                resumo["adiados"].append({
                    "nome": planta["nome"],
                    "score": novo_score,
                    "planta_id": planta["id"],
                })
            else:
                entrada = {"nome": planta["nome"], "score": novo_score, "planta_id": planta["id"]}
                if planta["evento_projetado_id"]:
                    entrada["evento_projetado_id"] = planta["evento_projetado_id"]
                resumo["novos_avisos"].append(entrada)
        else:
            # não cruzou hoje: verifica se cruzaria dentro da janela de
            # projeção (2 dias), pra manter o evento "previsão" em dia. A
            # simulação parte do score JÁ ATUALIZADO de hoje (novo_score),
            # não do score antigo em `planta` (que é o valor de antes do
            # ciclo rodar) — senão a projeção subestima quanto a planta já
            # avançou hoje.
            planta_com_score_atual = {**planta, "score": novo_score}
            data_prevista = simular_projecao(planta_com_score_atual, resposta, hoje)
            projetado_atual = planta["evento_projetado_id"]
            if data_prevista:
                acao = {
                    "nome": planta["nome"],
                    "planta_id": planta["id"],
                    "data_prevista": data_prevista,
                    "acao": "atualizar" if projetado_atual else "criar",
                }
                if projetado_atual:
                    acao["evento_projetado_id"] = projetado_atual
                resumo["projecoes"].append(acao)
            elif projetado_atual:
                resumo["projecoes"].append({
                    "acao": "cancelar",
                    "nome": planta["nome"],
                    "planta_id": planta["id"],
                    "evento_projetado_id": projetado_atual,
                })

    return resumo
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python3 -m pytest tests/test_motor.py -v`
Expected: PASS (todos, incluindo os já existentes de score/idempotência/cache de clima)

- [ ] **Step 5: Rodar a suíte completa**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add motor.py tests/test_motor.py
git commit -m "feat: integra projecao de 2 dias e promocao de evento projetado no ciclo diario"
```

---

### Task 6: `regar.py` limpa evento confirmado e projetado

**Files:**
- Modify: `regar.py`
- Test: `tests/test_regar.py`

**Interfaces:**
- Produces: `regar(conn, nome_planta, hoje=None)` retorna agora `{"nome", "score_anterior", "evento_calendario_id_removido", "evento_projetado_id_removido"}` — a chave nova aparece sempre (com `None` se não havia evento projetado).

- [ ] **Step 1: Escrever os testes que falham**

Atualizar o teste existente `test_regar_zera_score_e_registra_historico` em `tests/test_regar.py` pra incluir a nova chave no dict esperado:

```python
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
```

Adicionar um teste novo cobrindo os dois eventos ao mesmo tempo (caso raro mas possível: promoção ainda não rodou e a planta já foi regada manualmente):

```python
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
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `python3 -m pytest tests/test_regar.py -v`
Expected: FAIL — `resultado` não tem `evento_projetado_id_removido`, `KeyError` nos testes novos.

- [ ] **Step 3: Implementar**

Substituir `regar.py` inteiro por:

```python
"""Marca uma planta como regada: zera o score e limpa os lembretes
pendentes (confirmado e/ou projetado)."""
import datetime
import json
import sys

import db


def regar(conn, nome_planta, hoje=None):
    hoje = hoje or datetime.date.today()
    planta = db.obter_planta(conn, nome_planta)
    if planta is None:
        raise ValueError(f"Planta '{nome_planta}' não encontrada.")

    evento_confirmado_anterior = planta["evento_calendario_id"]
    evento_projetado_anterior = planta["evento_projetado_id"]
    score_anterior = planta["score"]

    db.registrar_rega(conn, planta["id"], hoje.isoformat(), score_anterior)
    db.atualizar_score(conn, planta["id"], 0)
    db.limpar_evento_calendario(conn, planta["id"])
    db.limpar_evento_projetado(conn, planta["id"])

    return {
        "nome": nome_planta,
        "score_anterior": score_anterior,
        "evento_calendario_id_removido": evento_confirmado_anterior,
        "evento_projetado_id_removido": evento_projetado_anterior,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Uso: python3 regar.py "Nome da planta"')
        sys.exit(1)

    conexao = db.conectar()
    resultado = regar(conexao, sys.argv[1])
    print(json.dumps(resultado, ensure_ascii=False, indent=2))

    eventos_pendentes = [
        e for e in (
            resultado["evento_calendario_id_removido"],
            resultado["evento_projetado_id_removido"],
        )
        if e is not None
    ]
    if eventos_pendentes:
        lista = ", ".join(f'"{e}"' for e in eventos_pendentes)
        print(
            f"\nATENÇÃO: o(s) evento(s) {lista} ainda existe(m) no "
            "Google Calendar. Este script não apaga eventos (isso acontece na "
            "camada do agente, não aqui) — peça pro Claude apagar esse(s) "
            "evento(s) manualmente."
        )
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `python3 -m pytest tests/test_regar.py -v`
Expected: PASS

- [ ] **Step 5: Rodar a suíte completa**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add regar.py tests/test_regar.py
git commit -m "feat: regar() limpa evento confirmado e projetado juntos"
```

---

### Task 7: Migração real de produção (schema + retenção das 7 plantas)

**Files:** nenhum arquivo de código — execução direta contra o Turso de produção pelo controller (mesmo padrão da Task 11 da v1).

- [ ] **Step 1: Aplicar o schema v2 no banco real**

Como `criar_schema` agora chama `migrar_schema_v2` automaticamente (Task 1), basta rodar `db.criar_schema(conn)` contra o Turso de produção uma vez pra aplicar as duas colunas novas (idempotente — seguro rodar de novo):

```bash
export TURSO_DATABASE_URL="<url real>"
export TURSO_AUTH_TOKEN="<token real>"
python3 -c "
import db
conn = db.conectar()
db.criar_schema(conn)
plantas = db.listar_plantas(conn)
for p in plantas:
    print(p['nome'], '| retencao_substrato:', p['retencao_substrato'], '| evento_projetado_id:', p['evento_projetado_id'])
"
```

Expected: as 7 plantas aparecem com `retencao_substrato: media` (valor padrão) e `evento_projetado_id: None`.

- [ ] **Step 2: Perguntar ao usuário a retenção real de cada planta**

Já temos referência de 3 plantas pela conversa (Flor de Maio = alta, Orquídea Borboleta = baixa) — confirmar essas e perguntar as 5 restantes (Jiboia, Ora pro nobis, Palmeira raphis, Babosa, Tomate) usando o `AskUserQuestion`, com as opções `alta`/`media`/`baixa` e uma frase explicando cada uma (ex: "alta = retém bastante água, tipo esfagno; baixa = drena rápido, tipo areia ou casca de pinus").

- [ ] **Step 3: Gravar os valores reais**

Para cada planta, com o valor confirmado pelo usuário:

```bash
python3 -c "
import db
conn = db.conectar()
planta = db.obter_planta(conn, '<nome da planta>')
db.atualizar_retencao_substrato(conn, planta['id'], '<alta|media|baixa>')
"
```

- [ ] **Step 4: Confirmar o resultado final**

```bash
python3 -c "
import db
conn = db.conectar()
for p in db.listar_plantas(conn):
    print(p['nome'], '->', p['retencao_substrato'])
"
```

Expected: todas as 7 plantas com o valor de retenção correto, nenhuma em `media` por omissão (a menos que `media` seja mesmo o valor certo pra ela).

---

### Task 8: Atualizar o prompt da tarefa agendada

**Files:** nenhum arquivo de código — texto entregue ao usuário pra ele colar na tarefa agendada existente (mesma limitação da v1: `create_trigger`/`update_trigger` com credencial embutida é bloqueado pro Claude neste ambiente).

- [ ] **Step 1: Montar o texto atualizado do prompt**

O novo prompt precisa, além do que a v1 já faz (clonar/instalar dependências, exportar credenciais, rodar `main.py`, processar `novos_avisos`/`ainda_atrasadas`, enviar resumo):

1. Todo evento criado (confirmado ou projetado) usa horário marcado das 17h40 às 18h no dia relevante, não mais "dia inteiro".
2. Para cada entrada de `novos_avisos` que tem `evento_projetado_id`: **não** criar evento novo — chamar `mcp__Google_Calendar__update_event` no `evento_projetado_id` existente (título → `"💧 Regar: <nome>"`, descrição confirma o score), depois `db.promover_evento_projetado(conn, planta_id, evento_projetado_id)` via `python3 -c`.
3. Para cada entrada de `novos_avisos` **sem** `evento_projetado_id`: fluxo igual à v1 (criar evento confirmado do zero), mas já com horário 17h40–18h.
4. Para cada entrada de `resumo["projecoes"]`:
   - `acao == "criar"`: criar evento `"🌦️ Possível rega: <nome> (previsão)"` na `data_prevista`, 17h40–18h; guardar o id retornado com `db.marcar_evento_projetado(conn, planta_id, evento_id)`.
   - `acao == "atualizar"`: atualizar data/descrição do evento `evento_projetado_id` existente via `mcp__Google_Calendar__update_event`.
   - `acao == "cancelar"`: apagar o evento `evento_projetado_id` via `mcp__Google_Calendar__delete_event`; limpar com `db.limpar_evento_projetado(conn, planta_id)`.

- [ ] **Step 2: Entregar o texto pronto ao usuário**

Escrever o prompt completo (igual ao formato usado na v1 — texto corrido com todos os passos e os nomes exatos das ferramentas/funções) e enviar ao usuário via chat, junto com a instrução de onde colar (editar a tarefa agendada já existente "Calculadora de rega — ciclo diário", campo do prompt) e o lembrete de que ele precisa colar o token do Turso real no lugar do placeholder — a mesma restrição de segurança da v1 (Claude não pode criar/editar automações com credencial embutida).

---

### Task 9: Verificação ponta-a-ponta v2

**Files:** nenhum novo — validação manual contra o sistema real, mesmo padrão da Task 13 da v1.

- [ ] **Step 1: Rodar a suíte de testes completa**

Run: `python3 -m pytest -q`
Expected: todos os testes passam (53 da v1 + os novos desta v2).

- [ ] **Step 2: Simular uma planta a ~2 dias de cruzar 100**

```bash
python3 -c "
import db
conn = db.conectar()
planta = db.obter_planta(conn, '<planta com retencao alta, testando o amortecimento>')
db.atualizar_score(conn, planta['id'], <valor calculado pra cruzar em ~2 dias com o clima real do momento>)
"
python3 main.py
```

Expected: `resumo["projecoes"]` no JSON impresso mostra uma entrada `"acao": "criar"` pra essa planta, com uma `data_prevista` dentro dos próximos 2 dias.

- [ ] **Step 3: Criar o evento projetado manualmente (papel da camada do agente) e confirmar**

Usar `mcp__Google_Calendar__create_event` com o título `"🌦️ Possível rega: <nome> (previsão)"`, horário 17h40–18h na `data_prevista`; gravar o id com `db.marcar_evento_projetado`. Confirmar via `mcp__Google_Calendar__get_event` que o evento existe com o título e horário certos.

- [ ] **Step 4: Rodar `main.py` de novo e confirmar a atualização/promoção**

Rodar `python3 main.py` outra vez (mesmo dia ou simulando o dia seguinte com `hoje=` se for testar via `motor.rodar_ciclo` direto). Se a planta ainda não cruzou de verdade, confirmar que `resumo["projecoes"]` mostra `"acao": "atualizar"` com o `evento_projetado_id` certo. Forçar o score real pra cruzar 100 (`db.atualizar_score`) e rodar de novo: confirmar que a entrada aparece em `novos_avisos` com `evento_projetado_id` presente — atualizar o evento existente pra `"💧 Regar: <nome>"` e chamar `db.promover_evento_projetado`; confirmar via `get_event` que é o **mesmo** id de evento, só com o título/descrição mudados (sem duplicar).

- [ ] **Step 5: Confirmar a rega e checar que os dois campos somem**

```bash
python3 regar.py "<nome da planta>"
```

Expected: JSON mostra `evento_calendario_id_removido` (o antigo projetado, agora promovido) preenchido e `evento_projetado_id_removido: null`. Apagar o evento do Calendar via `mcp__Google_Calendar__delete_event` e confirmar via `get_event` que o status virou `"cancelled"`.

- [ ] **Step 6: Testar o cancelamento de uma projeção**

Repetir o Step 2/3 pra outra planta, depois forçar uma chuva forte simulada (via um teste manual com `clima.buscar_dados_climaticos` mockado, ou esperando um dia real de chuva) e confirmar que `resumo["projecoes"]` mostra `"acao": "cancelar"` pra ela; apagar o evento e chamar `db.limpar_evento_projetado`.

- [ ] **Step 7: Entregar o projeto atualizado**

Enviar os arquivos alterados via `SendUserFile` (ou o bundle git, seguindo a mesma mecânica da v1 já usada nesta sessão, já que `git push` continua bloqueado pro Claude neste ambiente) e, se o usuário quiser, gravar a cópia local via `device_commit_files`.
