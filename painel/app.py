"""Painel web do Calculadora de Rega de Planta — Streamlit."""
import logging
import os
import sys

import streamlit as st

# `streamlit run painel/app.py` executa este arquivo como script, o que só
# coloca a própria pasta `painel/` no sys.path — sem isso, `import db` (que
# está na raiz do repositório) e `from painel import logica` quebram.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import regar
from painel import logica

st.set_page_config(page_title="Painel de Rega", page_icon="🌿")

CORES = {"vermelho": "🔴", "amarelo": "🟡", "verde": "🟢"}

# Localmente, as credenciais vêm do `.env` (via python-dotenv, que
# db.conectar() já sabe ler). No Streamlit Community Cloud não há `.env` —
# as credenciais ficam em st.secrets, então usamos elas como fallback
# quando a variável de ambiente ainda não está setada. `.env` local tem
# prioridade quando os dois existem.
#
# st.secrets levanta StreamlitSecretNotFoundError se não existir NENHUM
# arquivo de secrets (comum ao rodar só com `.env`, sem
# `.streamlit/secrets.toml`) — por isso o acesso é protegido por
# try/except em vez de deixar isso derrubar o app inteiro.
def _obter_credencial(chave):
    """Lê uma credencial do ambiente (.env local) ou, se ausente, dos
    secrets do Streamlit (usado no deploy, onde não há .env)."""
    if chave in os.environ:
        return os.environ[chave]
    try:
        return st.secrets.get(chave)
    except Exception:
        return None


for _chave in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
    valor = _obter_credencial(_chave)
    if valor:
        os.environ[_chave] = valor


def _senha_configurada():
    """PAINEL_SENHA só existe nos secrets do Streamlit (nunca no `.env`,
    já que o painel é a única coisa que usa essa senha). Protegido contra
    a ausência total de arquivo de secrets, igual `_obter_credencial`."""
    try:
        return st.secrets.get("PAINEL_SENHA")
    except Exception:
        return None


@st.cache_resource
def _conexao():
    return db.conectar()


def _autenticado():
    return st.session_state.get("autenticado", False)


def _tela_login():
    st.title("🌿 Painel de Rega")

    senha_configurada = _senha_configurada()
    if not senha_configurada:
        st.error("PAINEL_SENHA não está configurada. Veja painel/README.md.")
        return

    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if senha == senha_configurada:
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")


def _tela_principal():
    st.title("🌿 Painel de Rega")

    try:
        conn = _conexao()
        plantas = db.listar_plantas(conn)
    except Exception:
        logging.exception("Falha ao acessar o banco de dados")
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
                        logging.exception(f"Falha ao registrar rega de {planta['nome']}")
                        st.error(f"Não consegui registrar a rega de {planta['nome']}. Tenta de novo.")


def main():
    if not _autenticado():
        _tela_login()
        return

    _tela_principal()


main()
