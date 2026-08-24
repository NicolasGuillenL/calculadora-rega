"""Painel web do Calculadora de Rega de Planta — Streamlit."""
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


def main():
    if not _autenticado():
        _tela_login()
        return

    _tela_principal()


main()
