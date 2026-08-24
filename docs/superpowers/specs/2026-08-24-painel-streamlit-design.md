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

Para isso não virar um evento "esquecido" para sempre, `regar()` (chamado
tanto pelo painel quanto pelo CLI/chat) passa a **enfileirar** os ids de
evento que remove numa tabela nova, `eventos_pendentes_limpeza`
(`db.enfileirar_evento_pendente_limpeza` / `db.listar_eventos_pendentes_limpeza`
/ `db.remover_evento_pendente_limpeza`), antes de limpar a referência na
planta. O **ciclo diário existente** (prompt da tarefa agendada) ganha um
passo novo: drenar essa fila — para cada item em
`db.listar_eventos_pendentes_limpeza`, apagar o evento correspondente no
Google Calendar e então remover o item da fila com
`db.remover_evento_pendente_limpeza`.

Essa é a versão corrigida do mecanismo; ver a nota abaixo sobre o que foi
rejeitado.

### Correção importante em relação à primeira versão desta spec

A primeira versão desta seção propunha detectar "regada fora do fluxo"
comparando `ultima_rega` da planta com a data de criação do evento
(`evento_calendario_id`/`evento_projetado_id` não-nulo **e** `ultima_rega`
mais recente que a criação do evento). Essa ideia foi **abandonada**: não
há coluna com a data de criação do evento para comparar, e a checagem não
distinguia "regada pelo painel, evento ainda não limpo" de "regada há
muito tempo, e por algum motivo o evento nunca foi limpo por outro
caminho" — cenários que pedem tratamentos diferentes. A fila
`eventos_pendentes_limpeza` resolve isso de forma explícita: `regar()`
enfileira exatamente os eventos que removeu, no momento em que os remove,
sem precisar inferir nada a partir de timestamps depois. **O mecanismo a
implementar no ciclo diário é a fila, não a comparação de `ultima_rega`.**

A fila em si (inserir/listar/remover) é lógica pura sobre o banco, então
tem teste automatizado (`tests/test_db.py`, `tests/test_regar.py`) — é a
parte desta mudança que ganha teste automatizado, conforme "Fora de
escopo" acima. O passo de drenagem no ciclo diário (que efetivamente
apaga o evento no Google Calendar) roda na camada do agente, como o resto
da integração com o Calendar — ver "## Automação diária" no `README.md`
raiz.

## Tratamento de erros

- Turso inacessível ao carregar a lista: mensagem amigável
  ("Não consegui acessar os dados agora, tenta de novo em instantes") em vez
  de stack trace.
- Senha errada: mensagem genérica de erro, sem detalhes.
- Falha ao registrar rega (ex.: conexão cai no meio do clique): mensagem de
  erro clara e a planta continua aparecendo com o estado anterior (o botão
  não assume sucesso antes de confirmar).

## Testes

- Teste automatizado (`pytest`) para a fila `eventos_pendentes_limpeza`
  descrita acima: enfileirar/listar/remover (`tests/test_db.py`) e o
  comportamento de `regar()` de enfileirar os eventos que remove
  (`tests/test_regar.py`).
- O restante do painel (autenticação, listagem, botão de regar) é validado
  manualmente por Nero rodando `streamlit run painel/app.py` localmente
  antes do deploy.
