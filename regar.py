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
