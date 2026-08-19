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
