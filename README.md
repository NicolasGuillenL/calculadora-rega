# Calculadora de Rega

Automação pessoal que calcula um "score de sede" pra cada planta com base
em regras fixas (umidade ideal, época do ano, exposição ao sol) e no clima
real da cidade onde a planta está (via Open-Meteo). Quando o score cruza
100, a planta está pronta pra ser regada. Os dados ficam num banco Turso
(SQLite na nuvem) e o histórico de score/rega fica registrado dia a dia.

## Rodando localmente

1. Instale as dependências:

   ```
   pip install -r requirements.txt
   ```

2. Configure o `.env` (veja `.env.example`) com as credenciais do Turso:

   ```
   TURSO_DATABASE_URL=libsql://seu-banco.turso.io
   TURSO_AUTH_TOKEN=coloque-seu-token-aqui
   CIDADE_PADRAO=Sao Paulo, SP
   ```

3. Rode o ciclo diário:

   ```
   python3 main.py
   ```

   Isso recalcula o score de cada planta cadastrada e imprime um resumo em
   JSON (plantas atualizadas, novos avisos, avisos adiados por causa de
   chuva prevista e avisos que já estavam pendentes).

## Confirmando uma rega

Depois de regar uma planta de verdade, confirme com:

```
python3 regar.py "Nome da planta"
```

Isso zera o score da planta e limpa o vínculo com o evento do Google
Calendar no banco. **Atenção:** o script não apaga o evento do Calendar
na hora — ele fica enfileirado numa tabela de limpeza pendente
(`eventos_pendentes_limpeza`) e é o **ciclo diário automatizado**
(`main.py`, rodando como tarefa agendada) quem drena essa fila e apaga
os eventos de fato do Calendar, o que pode levar até 1 dia. O próprio
`regar.py` avisa no terminal quando um evento foi enfileirado dessa
forma.

Existe também um painel web (`painel/`) que chama esse mesmo `regar()`
com um clique — veja `painel/README.md` para rodar ou publicar.

## Automação diária (tarefa agendada)

O ciclo (`main.py`) roda automaticamente uma vez por dia como tarefa
agendada. Cada execução:

- busca o clima do dia (e dos próximos dias) pra cada cidade das plantas
  cadastradas, usando a API gratuita do Open-Meteo;
- recalcula o score de cada planta que ainda não foi processada hoje;
- registra o histórico de scores no banco;
- devolve, em JSON, quais plantas cruzaram 100 (avisos novos), quais já
  tinham aviso pendente e quais tiveram o aviso adiado por causa de chuva
  prevista.

A integração com o Google Calendar (criar o evento de lembrete de rega,
ou apagá-lo quando a planta é regada) **não acontece no código Python
deste repositório** — ela é feita na camada do agente (Claude), que lê o
resumo em JSON e usa as ferramentas MCP do Google Calendar pra criar/
apagar os eventos correspondentes.
