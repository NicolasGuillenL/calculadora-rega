# Painel Web (Streamlit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um painel web em Streamlit, hospedável de graça, para ver o status de rega das 7 plantas e registrar rega com um clique — sem duplicar a lógica que já existe em `db.py`/`regar.py`.

**Architecture:** Novo diretório `painel/` no mesmo repositório, reaproveitando `db.py`/`regar.py` da raiz. Como o painel não tem acesso ao Google Calendar (só a tarefa agendada/o assistente têm), `regar()` passa a enfileirar os eventos removidos numa tabela nova (`eventos_pendentes_limpeza`) para o ciclo diário existente processar depois — isso desacopla "registrar a rega no banco" (instantâneo, feito pelo painel) de "apagar o lembrete no Calendar" (até 1 dia depois, feito pela automação).

**Tech Stack:** Python, Streamlit, o banco Turso/SQLite já usado pelo resto do projeto.

**Spec:** `docs/superpowers/specs/2026-08-24-painel-streamlit-design.md`

## Global Constraints

- Painel fica em `painel/` no repositório `calculadora-rega`, reutilizando `db.py` e `regar.py` da raiz — nenhuma lógica de negócio duplicada.
- Painel nunca fala diretamente com a Google Calendar API (fora de escopo — ver spec).
- Autenticação: senha simples comparada com `st.secrets["PAINEL_SENHA"]`, guardada em `st.session_state`. Nunca commitar credenciais reais no repositório.
- Painel não mostra a data exata de previsão de rega — só o badge "previsão de regar em breve".
- `regar()` deve enfileirar `evento_calendario_id`/`evento_projetado_id` removidos em `eventos_pendentes_limpeza` antes de limpá-los de `plantas` — para toda chamada, não só as feitas pelo painel.
- Sem testes automatizados de interface Streamlit (validação manual, documentada em cada task). A lógica pura (fila de eventos, cálculo de status) tem teste automatizado.

---

### Task 1: Fila de eventos pendentes de limpeza

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nada de tasks anteriores (primeira task do plano).
- Produces:
  - `db.enfileirar_evento_pendente_limpeza(conn, evento_id) -> None`
  - `db.listar_eventos_pendentes_limpeza(conn) -> list[dict]` (cada dict tem `id`, `evento_id`, `criado_em`)
  - `db.remover_evento_pendente_limpeza(conn, pendente_id) -> None`

- [ ] **Step 1: Escrever os testes que devem falhar**

Adicione ao final de `tests/test_db.py`:

```python
def test_enfileirar_e_listar_evento_pendente_limpeza():
    conn = _conexao_teste()
    db.enfileirar_evento_pendente_limpeza(conn, "evento-abc")

    pendentes = db.listar_eventos_pendentes_limpeza(conn)

    assert len(pendentes) == 1
    assert pendentes[0]["evento_id"] == "evento-abc"


def test_listar_eventos_pendentes_limpeza_vazio_quando_nao_ha_fila():
    conn = _conexao_teste()
    assert db.listar_eventos_pendentes_limpeza(conn) == []


def test_remover_evento_pendente_limpeza():
    conn = _conexao_teste()
    db.enfileirar_evento_pendente_limpeza(conn, "evento-abc")
    pendente_id = db.listar_eventos_pendentes_limpeza(conn)[0]["id"]

    db.remover_evento_pendente_limpeza(conn, pendente_id)

    assert db.listar_eventos_pendentes_limpeza(conn) == []


def test_enfileirar_permite_varios_eventos_pendentes():
    conn = _conexao_teste()
    db.enfileirar_evento_pendente_limpeza(conn, "evento-1")
    db.enfileirar_evento_pendente_limpeza(conn, "evento-2")

    pendentes = {p["evento_id"] for p in db.listar_eventos_pendentes_limpeza(conn)}

    assert pendentes == {"evento-1", "evento-2"}
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_db.py -k pendente_limpeza -v`
Expected: FAIL com `AttributeError: module 'db' has no attribute 'enfileirar_evento_pendente_limpeza'`

- [ ] **Step 3: Adicionar a tabela nova ao schema**

Em `db.py`, dentro da string `SCHEMA` (depois do `CREATE TABLE IF NOT EXISTS historico_scores ...;` e antes das aspas triplas de fechamento), adicione:

```sql
CREATE TABLE IF NOT EXISTS eventos_pendentes_limpeza (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Como é uma tabela nova (não uma coluna nova numa tabela existente), `CREATE TABLE IF NOT EXISTS` já é idempotente por si só — não precisa de uma função de migração separada como `migrar_schema_v2`.

- [ ] **Step 4: Implementar as três funções**

Em `db.py`, adicione ao final do arquivo (depois de `atualizar_exposicao`):

```python
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
```

- [ ] **Step 5: Rodar os testes para confirmar que passam**

Run: `pytest tests/test_db.py -v`
Expected: PASS em todos os testes do arquivo, incluindo os quatro novos.

- [ ] **Step 6: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: adiciona fila de eventos pendentes de limpeza no Calendar"
```

---

### Task 2: `regar()` enfileira os eventos removidos

**Files:**
- Modify: `regar.py`
- Test: `tests/test_regar.py`

**Interfaces:**
- Consumes: `db.enfileirar_evento_pendente_limpeza(conn, evento_id)`, `db.listar_eventos_pendentes_limpeza(conn)` (Task 1).
- Produces: nenhuma interface nova — `regar()` mantém a mesma assinatura e o mesmo dict de retorno de antes; o efeito colateral novo (enfileirar) é observável só via `db.listar_eventos_pendentes_limpeza`.

- [ ] **Step 1: Escrever os testes que devem falhar**

Adicione ao final de `tests/test_regar.py`:

```python
def test_regar_enfileira_eventos_removidos_para_limpeza():
    conn = _conexao_teste()
    planta_id = db.inserir_planta(conn, PLANTA_EXEMPLO)
    db.marcar_evento_calendario(conn, planta_id, "evento-confirmado")
    db.marcar_evento_projetado(conn, planta_id, "evento-projetado")

    regar.regar(conn, "Jiboia", hoje=datetime.date(2026, 8, 18))

    pendentes = {p["evento_id"] for p in db.listar_eventos_pendentes_limpeza(conn)}
    assert pendentes == {"evento-confirmado", "evento-projetado"}


def test_regar_nao_enfileira_nada_quando_nao_havia_eventos():
    conn = _conexao_teste()
    db.inserir_planta(conn, PLANTA_EXEMPLO)

    regar.regar(conn, "Jiboia", hoje=datetime.date(2026, 8, 18))

    assert db.listar_eventos_pendentes_limpeza(conn) == []
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_regar.py -k enfileira -v`
Expected: FAIL — `test_regar_enfileira_eventos_removidos_para_limpeza` falha porque `db.listar_eventos_pendentes_limpeza(conn)` volta vazio (nada foi enfileirado ainda).

- [ ] **Step 3: Atualizar `regar()` para enfileirar antes de limpar**

Em `regar.py`, troque a função `regar` inteira por:

```python
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

    for evento_id in (evento_confirmado_anterior, evento_projetado_anterior):
        if evento_id is not None:
            db.enfileirar_evento_pendente_limpeza(conn, evento_id)

    db.limpar_evento_calendario(conn, planta["id"])
    db.limpar_evento_projetado(conn, planta["id"])

    return {
        "nome": nome_planta,
        "score_anterior": score_anterior,
        "evento_calendario_id_removido": evento_confirmado_anterior,
        "evento_projetado_id_removido": evento_projetado_anterior,
    }
```

- [ ] **Step 4: Atualizar o aviso do CLI para refletir a limpeza automática**

Ainda em `regar.py`, no bloco `if __name__ == "__main__":`, troque o texto de aviso final (o `print` dentro de `if eventos_pendentes:`) por:

```python
    if eventos_pendentes:
        lista = ", ".join(f'"{e}"' for e in eventos_pendentes)
        print(
            f"\nO(s) evento(s) {lista} ainda existe(m) no Google Calendar, mas já "
            "foram enfileirados para limpeza automática: o próximo ciclo diário "
            "vai apagá-los do Calendar (pode levar até 1 dia)."
        )
```

- [ ] **Step 5: Rodar os testes para confirmar que passam**

Run: `pytest tests/test_regar.py -v`
Expected: PASS em todos os testes do arquivo, incluindo os dois novos.

- [ ] **Step 6: Rodar a suíte inteira pra garantir que nada mais quebrou**

Run: `pytest -v`
Expected: PASS em todos os testes do repositório.

- [ ] **Step 7: Commit**

```bash
git add regar.py tests/test_regar.py
git commit -m "feat: regar() enfileira eventos removidos para limpeza automática"
```

---

### Task 3: Lógica de status da planta (`painel/logica.py`)

**Files:**
- Create: `painel/__init__.py`
- Create: `painel/logica.py`
- Test: `tests/test_logica_painel.py`

**Interfaces:**
- Consumes: nada (função pura, só recebe um dict de planta no formato retornado por `db.obter_planta`/`db.listar_plantas` — precisa das chaves `evento_calendario_id` e `evento_projetado_id`).
- Produces: `logica.calcular_status(planta) -> tuple[str, str]` — retorna `(cor, texto)`, onde `cor` é uma de `"vermelho"`, `"amarelo"`, `"verde"`.

- [ ] **Step 1: Criar o pacote `painel` vazio**

Crie o arquivo `painel/__init__.py` com conteúdo vazio.

- [ ] **Step 2: Escrever os testes que devem falhar**

Crie `tests/test_logica_painel.py`:

```python
from painel import logica


def test_status_vermelho_quando_tem_evento_calendario():
    planta = {"evento_calendario_id": "evento-1", "evento_projetado_id": None}

    cor, texto = logica.calcular_status(planta)

    assert cor == "vermelho"
    assert texto == "Precisa regar agora"


def test_status_amarelo_quando_tem_evento_projetado():
    planta = {"evento_calendario_id": None, "evento_projetado_id": "proj-1"}

    cor, texto = logica.calcular_status(planta)

    assert cor == "amarelo"
    assert texto == "Previsão de regar em breve"


def test_status_verde_quando_nao_tem_nenhum_evento():
    planta = {"evento_calendario_id": None, "evento_projetado_id": None}

    cor, texto = logica.calcular_status(planta)

    assert cor == "verde"
    assert texto == "Tranquila"


def test_status_vermelho_tem_prioridade_sobre_projetado():
    # Não deveria acontecer na prática (marcar_evento_projetado só roda
    # quando não há evento confirmado), mas se os dois estiverem
    # preenchidos ao mesmo tempo, "precisa regar agora" vence.
    planta = {"evento_calendario_id": "evento-1", "evento_projetado_id": "proj-1"}

    cor, texto = logica.calcular_status(planta)

    assert cor == "vermelho"
```

- [ ] **Step 3: Rodar os testes para confirmar que falham**

Run: `pytest tests/test_logica_painel.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'painel.logica'`

- [ ] **Step 4: Implementar `calcular_status`**

Crie `painel/logica.py`:

```python
"""Lógica pura do painel (sem dependência do Streamlit) — fica separada de
`app.py` pra ser testável sem precisar rodar a interface."""


def calcular_status(planta):
    """Retorna (cor, texto) a partir do estado de rega da planta.

    `planta` é um dict no formato de `db.obter_planta`/`db.listar_plantas`
    (precisa ter as chaves `evento_calendario_id` e `evento_projetado_id`).
    `cor` é uma de "vermelho", "amarelo", "verde".
    """
    if planta["evento_calendario_id"]:
        return "vermelho", "Precisa regar agora"
    if planta["evento_projetado_id"]:
        return "amarelo", "Previsão de regar em breve"
    return "verde", "Tranquila"
```

- [ ] **Step 5: Rodar os testes para confirmar que passam**

Run: `pytest tests/test_logica_painel.py -v`
Expected: PASS nos quatro testes.

- [ ] **Step 6: Commit**

```bash
git add painel/__init__.py painel/logica.py tests/test_logica_painel.py
git commit -m "feat: lógica de status de rega do painel"
```

---

### Task 4: Painel Streamlit — autenticação e listagem

**Files:**
- Create: `painel/app.py`
- Create: `painel/README.md`
- Create: `.streamlit/secrets.toml.example`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `db.conectar()`, `db.listar_plantas(conn)` (já existentes em `db.py`); `logica.calcular_status(planta)` (Task 3).
- Produces: `painel/app.py` como ponto de entrada do Streamlit (`streamlit run painel/app.py`). Nenhuma outra task consome `app.py` como código — é a interface final.

- [ ] **Step 1: Adicionar o Streamlit às dependências**

Em `requirements.txt`, adicione a linha:

```
streamlit>=1.38,<2
```

- [ ] **Step 2: Criar o arquivo de exemplo de secrets**

Crie `.streamlit/secrets.toml.example` na raiz do repositório:

```toml
TURSO_DATABASE_URL = "libsql://seu-banco.turso.io"
TURSO_AUTH_TOKEN = "seu-token-aqui"
PAINEL_SENHA = "escolha-uma-senha-forte"
```

- [ ] **Step 3: Criar `painel/app.py`**

```python
"""Painel web do Calculadora de Rega de Planta — Streamlit."""
import os
import sys

import streamlit as st

# `streamlit run painel/app.py` executa este arquivo como script, o que só
# coloca a própria pasta `painel/` no sys.path — sem isso, `import db` (que
# está na raiz do repositório) e `from painel import logica` quebram.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from painel import logica

st.set_page_config(page_title="Painel de Rega", page_icon="🌿")

CORES = {"vermelho": "🔴", "amarelo": "🟡", "verde": "🟢"}

# Streamlit Community Cloud entrega credenciais via st.secrets, não via
# variáveis de ambiente — db.conectar() só sabe ler de os.environ (via
# python-dotenv), então preenchemos o ambiente a partir de st.secrets aqui.
# setdefault: se já existir um .env local com essas variáveis (rodando o
# painel na sua própria máquina), ele continua valendo.
for _chave in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
    if _chave in st.secrets:
        os.environ.setdefault(_chave, st.secrets[_chave])


def _autenticado():
    return st.session_state.get("autenticado", False)


def _tela_login():
    st.title("🌿 Painel de Rega")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if senha == st.secrets.get("PAINEL_SENHA"):
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")


def _tela_principal():
    st.title("🌿 Painel de Rega")

    try:
        conn = db.conectar()
        plantas = db.listar_plantas(conn)
    except Exception:
        st.error("Não consegui acessar os dados agora. Tenta de novo em instantes.")
        return

    for planta in sorted(plantas, key=lambda p: p["nome"]):
        cor, texto = logica.calcular_status(planta)
        st.write(f"{CORES[cor]} **{planta['nome']}** — score {planta['score']:.1f} — {texto}")


def main():
    if not _autenticado():
        _tela_login()
        return

    _tela_principal()


main()
```

- [ ] **Step 4: Criar `painel/README.md`**

```markdown
# Painel de Rega (Streamlit)

Painel web para ver o status das plantas e registrar rega com um clique.

## Rodar localmente

1. Na raiz do repositório, copie `.streamlit/secrets.toml.example` para
   `.streamlit/secrets.toml` e preencha com as credenciais reais do Turso e
   a senha que você quer usar no painel.
2. Instale as dependências: `pip install -r requirements.txt` (use
   `--break-system-packages` se necessário, ou um virtualenv).
3. Rode: `streamlit run painel/app.py`
4. Abra o link que aparecer no terminal (geralmente http://localhost:8501).

## Publicar no Streamlit Community Cloud

1. Suba este repositório pro GitHub, branch `main`.
2. Em https://share.streamlit.io, clique em "New app", escolha o
   repositório e o arquivo `painel/app.py` como ponto de entrada.
3. Em "Advanced settings" → "Secrets", cole o conteúdo do seu
   `.streamlit/secrets.toml` (as mesmas 3 chaves: `TURSO_DATABASE_URL`,
   `TURSO_AUTH_TOKEN`, `PAINEL_SENHA`).
4. Publique. Todo `git push` na `main` que mexer em `painel/` atualiza o
   app publicado automaticamente.
```

- [ ] **Step 5: Testar manualmente**

Rode `streamlit run painel/app.py` localmente (com um `.streamlit/secrets.toml`
válido apontando pro banco de teste ou pro banco real). Confirme:
- Sem digitar senha (ou com senha errada), a tela de login aparece e mostra
  "Senha incorreta." quando errada.
- Com a senha certa, a lista das 7 plantas aparece, cada uma com score e o
  emoji/texto de status correto (compare com o que `db.obter_planta` mostra
  para uma planta de cada cor).
- Fechar a aba e abrir de novo pede a senha outra vez.

- [ ] **Step 6: Commit**

```bash
git add painel/app.py painel/README.md .streamlit/secrets.toml.example requirements.txt
git commit -m "feat: painel Streamlit com autenticação e listagem de plantas"
```

---

### Task 5: Painel Streamlit — botão "Reguei"

**Files:**
- Modify: `painel/app.py`

**Interfaces:**
- Consumes: `regar.regar(conn, nome_planta)` (já existente, agora enfileirando eventos pendentes por causa da Task 2).
- Produces: nenhuma — é a última task do plano.

- [ ] **Step 1: Adicionar o botão à tela principal**

Em `painel/app.py`, adicione `import regar` junto dos outros imports (depois de `import db`):

```python
import db
import regar
from painel import logica
```

Troque a função `_tela_principal` inteira por:

```python
def _tela_principal():
    st.title("🌿 Painel de Rega")

    try:
        conn = db.conectar()
        plantas = db.listar_plantas(conn)
    except Exception:
        st.error("Não consegui acessar os dados agora. Tenta de novo em instantes.")
        return

    for planta in sorted(plantas, key=lambda p: p["nome"]):
        cor, texto = logica.calcular_status(planta)
        coluna_info, coluna_botao = st.columns([4, 1])
        with coluna_info:
            st.write(f"{CORES[cor]} **{planta['nome']}** — score {planta['score']:.1f} — {texto}")
        with coluna_botao:
            if cor == "vermelho":
                if st.button("Reguei", key=f"regar_{planta['id']}"):
                    try:
                        regar.regar(conn, planta["nome"])
                        st.rerun()
                    except Exception:
                        st.error(f"Não consegui registrar a rega de {planta['nome']}. Tenta de novo.")
```

- [ ] **Step 2: Testar manualmente**

Rode `streamlit run painel/app.py`. Confirme:
- O botão "Reguei" só aparece nas plantas 🔴 (score ≥ 100, com
  `evento_calendario_id`).
- Clicar nele zera o score na tela (recarrega e mostra 🟢/score 0.0) e o
  botão some.
- Depois de clicar, rode
  `python3 -c "import db; conn = db.conectar(); print(db.listar_eventos_pendentes_limpeza(conn))"`
  e confirme que o evento que estava na planta apareceu na fila.

- [ ] **Step 3: Rodar a suíte de testes inteira**

Run: `pytest -v`
Expected: PASS em todos os testes do repositório (a suíte inteira, não só os
novos — nenhuma mudança deste plano deveria ter quebrado nada existente).

- [ ] **Step 4: Commit**

```bash
git add painel/app.py
git commit -m "feat: botão Reguei no painel Streamlit"
```
