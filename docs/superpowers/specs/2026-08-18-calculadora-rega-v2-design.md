# Calculadora de Rega de Planta v2 — Retenção de Substrato + Agenda Proativa

Data: 2026-08-18
Status: Aprovado para planejamento
Depende de: `docs/superpowers/specs/2026-08-18-calculadora-rega-design.md` (v1, já implementada e em produção)

## Contexto e objetivo

A v1 já roda em produção: score de sede por planta, clima real via Open-Meteo, aviso reativo (cria evento no Google Calendar só quando a planta *já* cruzou score 100 hoje). Duas limitações identificadas pelo usuário depois de usar o sistema:

1. O modificador climático não considera o substrato onde a planta está plantada — só a necessidade da planta (`umidade_ideal_pct`) e a exposição. Na prática, substratos diferentes retêm água de forma muito diferente (ex: musgo esfagno vivo retém muito; casca de pinus e solo arenoso retêm pouco), o que muda o quanto a evapotranspiração (et0) realmente seca a planta por dia.
2. O aviso só existe no dia em que a planta já cruzou 100 — não há antecedência na agenda. O usuário quer saber com ~2 dias de antecedência que uma planta provavelmente vai precisar de água, pra poder se planejar, com o lembrete do Calendar disparando no horário em que costuma estar em casa (~17h40–18h).

Objetivo desta v2: adicionar um fator de retenção de substrato à fórmula climática, e um mecanismo de projeção de 2 dias que cria/atualiza/cancela eventos "previsão" no Google Calendar do usuário conforme a previsão do tempo evolui, promovendo o evento projetado a evento confirmado quando a planta de fato cruza 100.

## Decisões validadas com o usuário

- Retenção de substrato: 3 níveis (`alta`/`media`/`baixa`), não um número livre — consistente com o padrão já usado para exposição.
- Retenção afeta só o termo de secagem (et0/sol/vento) da fórmula climática, não o efeito da chuva medida.
- Horizonte de projeção: 2 dias — reaproveita a mesma janela de previsão que a v1 já busca (`past_days=1`, `forecast_days=2`), sem chamada extra à API.
- O score real da planta continua reagindo **só a chuva medida** (como corrigido na revisão final da v1) — a previsão de chuva não desconta o score antecipadamente. Ela entra apenas na simulação de projeção, que decide sobre o evento no Calendar, não sobre o score gravado.
- Não existe uma segunda execução diária às 17h40 — é o mesmo ciclo das 7h que cria os eventos já com horário marcado (17h40–18h) nesse dia, pra o lembrete nativo do Calendar disparar na hora certa.
- Todo evento de rega (projetado ou confirmado) passa a ser criado como evento com horário marcado (17h40–18h) no dia relevante, em vez de "dia inteiro" como na v1 — mudança de formato que vale tanto pros eventos novos (projetados) quanto pros reativos (mesmo dia), por consistência.
- Evento projetado que se confirma vira o evento real (mesmo ID no Calendar, só atualiza título/descrição) — nunca cancela-e-recria.
- Evento projetado que deixa de ser projetado (previsão mudou, planta não cruza mais 100 na janela) é cancelado, sem recriação automática — a projeção do dia seguinte decide de novo, do zero.
- Título do evento distingue os dois estados: "🌦️ Possível rega: X (previsão)" enquanto projetado, "💧 Regar: X" quando confirmado — visível na agenda sem precisar abrir o evento.

## Modelo de dados (alterações na tabela `plantas`)

```sql
ALTER TABLE plantas ADD COLUMN retencao_substrato TEXT NOT NULL DEFAULT 'media';
ALTER TABLE plantas ADD COLUMN evento_projetado_id TEXT;
```

`retencao_substrato` aceita `'alta'`, `'media'`, `'baixa'`. `evento_projetado_id` funciona exatamente como `evento_calendario_id` (nullable, guarda o ID do evento no Calendar), mas para o evento ainda não confirmado — os dois campos nunca ficam preenchidos ao mesmo tempo para a mesma planta.

Diferente da v1 (onde o schema nunca mudou depois de criado), esta mudança precisa de uma migração real contra o banco Turso já em produção — `db.criar_schema` usa `CREATE TABLE IF NOT EXISTS`, que não adiciona colunas a uma tabela já existente. Um passo de migração dedicado (`ALTER TABLE`, com tratamento pra rodar com segurança mesmo se já tiver sido aplicado antes) faz parte do plano de implementação, junto com preencher `retencao_substrato` das 7 plantas reais já cadastradas (valores coletados do usuário, como foi feito com `exposicao` na v1 — já temos três referências: Flor de Maio = alta, Orquídea Borboleta = baixa, suculentas provavelmente baixa).

## Fórmula climática (mudança em `clima.py`)

Novo multiplicador `fator_retencao`, aplicado junto com `fator_planta` (que já existe) no termo de secagem:

| `retencao_substrato` | `fator_retencao` |
|---|---|
| `alta` | 0.6 |
| `media` | 1.0 |
| `baixa` | 1.3 |

```
secagem = et0 * fator_planta * fator_retencao * exposicao_fator
```

(os ajustes de vento/UV/umidade relativa/nebulosidade que já existem em `calcular_incremento_clima` continuam aplicados sobre esse `secagem`, sem mudança). O efeito da chuva medida (`efeito_chuva`) não é afetado por `fator_retencao` — continua igual à v1.

Os valores 0.6/1.3 são um ponto de partida, calibrável depois de observar o comportamento real (mesmo espírito das outras constantes da v1, como `FATOR_CHUVA` e os limiares de vento/UV).

## Simulação de projeção (nova função em `motor.py`)

`simular_projecao(planta, resposta_clima, hoje)`: função pura (sem I/O), separada de `rodar_ciclo`. Para uma planta que não tem `evento_calendario_id` (não está atrasada hoje), simula o score avançando dia a dia para os próximos até 2 dias disponíveis na resposta do Open-Meteo já buscada (a mesma chamada usada pelo ciclo real, sem request adicional), usando a mesma fórmula de `calcular_incremento_base` + `calcular_incremento_clima` — incluindo a chuva **prevista** (não medida) para esses dias futuros, já que ainda não aconteceram. Não grava nada em `historico_scores` nem em `plantas.score` — é só uma projeção em memória que retorna, se aplicável, a data em que o score projetado cruzaria 100.

`rodar_ciclo` passa a chamar essa função para cada planta elegível (sem `evento_calendario_id`) depois de processar o score real do dia, e monta um novo bucket no resumo, `resumo["projecoes"]`, com uma entrada por planta cujo resultado mudou o estado do evento projetado (precisa criar, atualizar ou cancelar), incluindo o que a camada do agente precisa fazer. As três primeiras linhas da tabela abaixo vêm da simulação (`simular_projecao`); as duas últimas são resultado do cálculo do score **real** do dia (já existente desde a v1), incluídas aqui só para deixar claro como se conectam com o ciclo de vida do evento projetado:

| Situação | Origem | Ação da camada do agente |
|---|---|---|
| Projeta cruzar 100 em até 2 dias, planta sem projetado nem confirmado | Simulação | Criar evento "🌦️ Possível rega: X (previsão)", horário 17h40–18h no dia projetado; gravar `evento_projetado_id` |
| Já tem `evento_projetado_id`, nova simulação ainda projeta cruzar (data pode ter mudado) | Simulação | Atualizar data/descrição do mesmo evento |
| Já tem `evento_projetado_id`, nova simulação não projeta mais cruzar | Simulação | Cancelar o evento; limpar `evento_projetado_id` |
| Score real cruza 100 hoje **e não foi adiado**, planta já tinha `evento_projetado_id` | Score real | Atualizar o mesmo evento (título → "💧 Regar: X", descrição confirma); mover o ID de `evento_projetado_id` para `evento_calendario_id` |
| Score real cruza 100 hoje **e não foi adiado**, planta não tinha nada | Score real | Fluxo igual à v1: criar evento confirmado, horário 17h40–18h |

O mecanismo de adiamento já existente na v1 (`deve_adiar_aviso`, que adia a notificação — não o score — quando a chance de chuva nas próximas 48h é alta) continua funcionando sem alteração, de forma independente da simulação de projeção: ele decide sobre o aviso do **score real** de hoje; a simulação decide sobre o evento **futuro**. Se o cruzamento real de hoje é adiado (`resumo["adiados"]`), a promoção projetado→confirmado **não acontece** nesse ciclo — como a planta não tem `evento_calendario_id`, a lógica de bucket já existente na v1 a coloca em `adiados` normalmente (independente de ela ter ou não um `evento_projetado_id`), e o evento projetado (se existir) permanece como está até a simulação do dia seguinte decidir se cancela ou mantém.

`regar()` (em `regar.py`) passa a limpar os dois campos (`evento_calendario_id` e `evento_projetado_id`) e retornar ambos os IDs não nulos para a camada do agente apagar — mesma mecânica de aviso já existente na v1 (o script não apaga sozinho).

## Automação diária — mudança no prompt da tarefa agendada

O prompt da tarefa das 7h (hoje só roda `main.py` e processa `novos_avisos`/`ainda_atrasadas`) ganha um passo novo: processar também `resumo["projecoes"]`, executando a ação de Calendar indicada em cada entrada (criar/atualizar/cancelar) e gravando o resultado de volta no banco via `db.py` (novos helpers: `marcar_evento_projetado`, `limpar_evento_projetado`, além de promover projetado→confirmado). Continua sendo uma única execução diária — nenhuma automação nova.

## Fora de escopo (v2)

- Desconto antecipatório no score baseado em probabilidade de chuva (decidido explicitamente que não — score só reage a chuva medida).
- Ajuste automático dos multiplicadores de retenção com base em histórico observado (calibração manual, como os outros parâmetros).
- Projeção além de 2 dias (exigiria pedir uma janela maior de previsão à API do Open-Meteo).

## Testes

- `test_clima.py`: novos testes para `fator_retencao` em `calcular_incremento_clima`, isolando o efeito de cada nível de retenção (mesmo padrão dos testes de `fator_planta`).
- `test_motor.py`: testes para `simular_projecao` cobrindo os 5 casos da tabela de ciclo de vida (cria projetado, atualiza projetado, cancela projetado, promove projetado→confirmado, cruza sem projeção prévia), com clima mockado, sem rede real.
- `test_db.py`: testes para os novos helpers (`marcar_evento_projetado`, `limpar_evento_projetado`) e para a migração `ALTER TABLE` (idempotente — rodar duas vezes não deve quebrar).
- `test_regar.py`: teste atualizado garantindo que `regar()` limpa e retorna os dois campos de evento quando ambos ou só um está preenchido.
- Migração real do Turso (schema + preenchimento de `retencao_substrato` das 7 plantas) validada manualmente contra o banco de verdade, como na v1.
