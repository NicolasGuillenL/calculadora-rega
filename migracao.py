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
