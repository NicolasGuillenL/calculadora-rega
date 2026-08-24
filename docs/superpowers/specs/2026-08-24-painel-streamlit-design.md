# Painel Web (Streamlit) — Spec de Design

**Status:** Aprovado por Nero em conversa (24/08/2026)

## Contexto

O sistema "Calculadora de Rega de Planta" hoje roda inteiramente via automação
(tarefa agendada diária que calcula o score de cada planta e mexe no Google
Calendar) e via conversa direta com o assistente (para regar uma planta
manualmente, tirar dúvidas, etc). Não existe hoje nenhuma interface visual —
tudo passa pelo chat ou por scripts Python de linha de comando.

Nero quer um painel web simples para ver o status das plantas e registrar
rega com um clique, acessível de qualquer lugar (não só da rede de casa).

## Objetivo

Um app Streamlit, hospedado gratuitamente no Streamlit Community Cloud, que:

1. Mostra as 7 plantas com score atual e status (precisa regar agora /
   previsão de regar em breve com data / tranquila).
2. Permite registrar a rega de uma planta com um clique, chamando a mesma
   lógica que já existe (`regar.regar()`), sem duplicar regras.
3. Fica protegido por senha simples, já que fica acessível pela internet.

## Fora de escopo (YAGNI)

- Autenticação com conta Google — senha simples resolve para uso pessoal de
  uma pessoa só.
- O painel falar diretamente com a Google Calendar API — mantém a
  arquitetura atual (Calendar só é tocado pela automação diária existente /
  pelo assistente via chat), evitando configurar credenciais OAuth do Google
  só para isso.
- Qualquer funcionalidade de múltiplos usuários, múltiplas contas ou
  múltiplas cidades/instalações.
- Testes automatizados de interface (é um app pequeno e pessoal; a lógica
  de interface é fina o suficiente para verificar manualmente).

## Arquitetura

Novo diretório `painel/` no mesmo repositório `calculadora-rega`, com um
único app Streamlit (`painel/app.py`) que importa e reutiliza `db.py` e
`regar.py` da raiz do repositório — nenhuma lógica de negócio é duplicada
ou reescrita.

O app se conecta ao **mesmo banco Turso** já usado pela automação diária.
Credenciais (`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`) e a senha do painel
(`PAINEL_SENHA`) ficam nos "secrets" do Streamlit Community Cloud — nunca
commitadas no repositório.

Deploy: Streamlit Community Cloud, conectado diretamente ao repositório
GitHub de Nero (`main`). Cada push em `main` que toque `painel/` atualiza o
app publicado automaticamente.

## Autenticação

Tela de senha antes de qualquer conteúdo:

- Campo de senha (`st.text_input(type="password")`).
- Compara com `st.secrets["PAINEL_SENHA"]`.
- Se correta, marca `st.session_state["autenticado"] = True` e mostra o
  painel; senão, mostra "Senha incorreta" (sem indicar qual é a senha
  certa) e mantém o campo.
- `st.session_state` mantém a pessoa autenticada apenas durante a sessão do
  navegador (fecha a aba → precisa digitar de novo).

## Tela principal

Lista das 7 plantas (via `db.listar_plantas`), uma linha por planta, cada
uma mostrando:

- Nome.
- Score atual (arredondado a 1 casa decimal).
- Status, calculado a partir do score e dos campos de evento:
  - 🔴 **Precisa regar agora** — `score >= 100` (tem `evento_calendario_id`).
  - 🟡 **Previsão de regar em breve** — tem `evento_projetado_id`. O painel
    não tem acesso ao Google Calendar (só o assistente/tarefa agendada têm),
    então não é possível ler a data exata prevista sem duplicar essa
    integração — decisão: o painel mostra só o aviso "previsão de regar em
    breve", sem a data exata; quem quiser a data exata continua vendo na
    própria Agenda ou perguntando ao assistente. Guardar a data prevista
    também no banco (para o painel exibi-la) fica fora de escopo por YAGNI —
    pode ser revisitado depois se fizer falta na prática.
  - 🟢 **Tranquila** — nenhum dos dois casos acima.
- Um botão **"Reguei"**, visível só para plantas com `score >= 100`, que
  chama `regar.regar(conn, nome_da_planta)` e re-renderiza a lista com o
  novo estado (score zerado, sem badge de pendência).

## Rega pelo painel vs. rega pelo chat — diferença aceita

Regar pelo painel **não** apaga o evento correspondente no Google Calendar
na hora — isso só acontece hoje através do assistente (via chat, com acesso
às ferramentas de Calendar) ou da tarefa agendada diária. Nero confirmou que
está OK com até 1 dia de atraso nesse caso específico.

Para isso não virar um evento "esquecido" para sempre, o **ciclo diário
existente** (prompt da tarefa agendada) ganha um passo novo: antes de
processar `novos_avisos`/`ainda_atrasadas`/`projecoes`, verificar se alguma
planta tem `evento_calendario_id` ou `evento_projetado_id` não-nulo **e**
`ultima_rega` mais recente que a criação desse evento (ou seja: foi regada
depois que o evento foi criado, mas o evento nunca foi limpo — sinal de que
foi regada pelo painel). Para cada uma encontrada: apaga o evento no
Calendar e limpa a referência no banco (`db.limpar_evento_calendario` /
`db.limpar_evento_projetado`).

Essa checagem é lógica pura sobre o banco (comparação de datas), então tem
teste automatizado — é a única parte desta mudança que ganha teste
automatizado, conforme "Fora de escopo" acima.

## Tratamento de erros

- Turso inacessível ao carregar a lista: mensagem amigável
  ("Não consegui acessar os dados agora, tenta de novo em instantes") em vez
  de stack trace.
- Senha errada: mensagem genérica de erro, sem detalhes.
- Falha ao registrar rega (ex.: conexão cai no meio do clique): mensagem de
  erro clara e a planta continua aparecendo com o estado anterior (o botão
  não assume sucesso antes de confirmar).

## Testes

- Teste automatizado (`pytest`) só para a nova checagem de "planta regada
  fora do fluxo" descrita acima — dado um banco com uma planta com
  `evento_calendario_id` setado e `ultima_rega` posterior à criação do
  evento, a função de checagem deve identificá-la como pendente de limpeza;
  dado o caso normal (sem rega recente), não deve identificá-la.
- O restante do painel (autenticação, listagem, botão de regar) é validado
  manualmente por Nero rodando `streamlit run painel/app.py` localmente
  antes do deploy.
