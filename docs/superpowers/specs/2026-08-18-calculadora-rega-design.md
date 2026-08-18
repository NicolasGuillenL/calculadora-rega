# Calculadora de Rega de Planta — Design

Data: 2026-08-18
Status: Aprovado para planejamento

## Contexto e objetivo

O projeto já tem um "banco" informal (`Bd_Plantas.ipynb`): um dict Python `plantas` com 8 plantas cadastradas, cada uma com atributos de perfil (temperatura ideal, umidade ideal, épocas de floração/crescimento/poda/replantio/mudas) e campos de rega (`ultima_Rega`, `proxima_Rega`) hoje não preenchidos automaticamente. Há também um dict `Estações` com um erro de sintaxe (falta `=` na atribuição), que impede a célula de rodar por completo.

Objetivo: substituir o controle manual de "próxima rega" por um sistema de **score de sede** (0 a 100+) por planta, que sobe todo dia com base no perfil da planta e no clima real do local onde ela está, e zera quando a planta é regada. Quando o score cruza 100, o sistema avisa. Se a planta continuar sem ser regada, o score continua subindo e os avisos se repetem.

## Decisões já validadas com o usuário

- Armazenamento: **Turso** (SQLite hospedado, plano gratuito) — acessível tanto pela automação na nuvem quanto, futuramente, por um site/app, sem depender do PC do usuário estar ligado ou do Claude Desktop estar aberto.
- Localização: **cidade fixa**, configurada uma vez, resolvida para latitude/longitude via geocoding do Open-Meteo e guardada.
- Frequência: automação **1x por dia**, rodando como tarefa agendada do Claude (nuvem).
- Confirmação de rega: função explícita (`regar("nome_planta")`) chamada pelo usuário — não há fluxo de confirmação interativa via chat na v1.
- Motor de score: tabela de regras por atributo (não uma fórmula única de caixa-preta) — cada atributo do perfil da planta contribui com pontos/dia de forma explícita e editável.
- Clima: usar o máximo de variáveis disponíveis no Open-Meteo (gratuito, sem chave), com `et0_fao_evapotranspiration` como eixo principal e as demais como ajustes finos.

## Modelo de dados (Turso / SQLite)

```sql
CREATE TABLE plantas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    temperatura_ideal_c REAL,
    umidade_ideal_pct REAL,
    florescimento TEXT,      -- estação (ex: 'Primavera')
    crescimento TEXT,
    crescimento2 TEXT,
    poda TEXT,
    replantio TEXT,
    mudas TEXT,
    epoca_mudas TEXT,
    exposicao INTEGER NOT NULL DEFAULT 5,  -- 0, 5 ou 10
    cidade TEXT NOT NULL,                  -- localização usada para o clima desta planta
    score REAL NOT NULL DEFAULT 0,
    ultima_rega TEXT,                      -- data ISO (YYYY-MM-DD)
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE historico_regas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planta_id INTEGER NOT NULL REFERENCES plantas(id),
    data TEXT NOT NULL,                    -- data ISO
    score_no_momento REAL,                 -- score acumulado antes de zerar (indica atraso)
    origem TEXT NOT NULL DEFAULT 'manual'  -- 'manual' por enquanto; espaço para futuras origens
);

CREATE TABLE historico_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planta_id INTEGER NOT NULL REFERENCES plantas(id),
    data TEXT NOT NULL,
    incremento_base REAL,
    incremento_clima REAL,
    score_final REAL,
    et0 REAL,
    precipitacao_mm REAL,
    UNIQUE(planta_id, data)
);
```

`historico_scores` existe para depuração e transparência: permite ao usuário olhar por que o score subiu tanto num dia específico (ex: "choveu 5mm e o et0 foi 4.2").

## Motor de score

### 1. Incremento base diário (regras por atributo)

Definido como uma tabela de regras em código (`regras_score.py`), separada da lógica de cálculo, editável sem tocar no motor:

| Atributo | Condição | Efeito no score/dia |
|---|---|---|
| `umidade_ideal_pct` | ≥ 65% | +15 |
| `umidade_ideal_pct` | 45–64% | +10 |
| `umidade_ideal_pct` | < 45% | +6 |
| `crescimento` / `crescimento2` | mês atual bate com a estação | +5 (cada uma que bater) |
| `florescimento` | mês atual bate com a estação | +3 |

O nível de `umidade_ideal_pct` (alto/médio/baixo) também é usado como **fator multiplicador** no cálculo climático abaixo — evita duplicar a lógica de "quanto essa planta precisa de água".

### 2. Modificador climático (Open-Meteo)

Uma chamada diária à API de forecast (usando lat/long da cidade configurada, com `past_days` para capturar o dia anterior) traz:

| Variável | Papel | Efeito |
|---|---|---|
| `et0_fao_evapotranspiration` | Secagem combinada (sol+calor+vento+umidade) — eixo principal | `+ et0 × fator_planta × (exposicao/10)`, onde `fator_planta` = 1.5 (alta necessidade), 1.0 (média) ou 0.5 (baixa), usando os mesmos tiers de `umidade_ideal_pct` acima |
| `precipitation_sum` + `rain_sum` | Chuva do dia | `− chuva_mm × k × (exposicao/10)` (reduz o score; `k` calibrado para chuva forte quase zerar uma planta 100% exposta) |
| `precipitation_probability_max` (próx. 48h) | Chance de chover em breve | Se score projetado ≥ 90 e probabilidade ≥ 60%, **adia o aviso** (não dispara notificação ainda) |
| `windspeed_10m_max` | Vento forte | Bônus pequeno (~10-20% do termo et0) se acima de um limiar (ex: 20 km/h) — vento seca a superfície do solo em vasos mais rápido do que o et0 sozinho capta |
| `uv_index_max` | Sol direto intenso | Bônus pequeno se UV ≥ 8, escalado por exposição (planta indoor não sente) |
| `relative_humidity_2m` (média do dia) | Umidade do ar | Reforça secagem se < 40%; reduz se > 80% — é o principal efeito climático para plantas de exposição 0 (chuva não molha, mas o ar fica mais úmido) |
| `cloudcover_mean` | Nebulosidade | Reduz levemente a secagem em dias nublados sem chuva registrada |

Todas as variáveis vêm da mesma chamada à API (um único request HTTP por dia). O `et0` carrega o peso principal; as demais entram como ajustes de ~10-20% para não desestabilizar o cálculo.

Score final do dia = `score_anterior + incremento_base + incremento_clima`, sem teto — passar de 100 é o próprio indicador de atraso (quanto maior, mais atrasada a rega).

### 3. Regar

`regar(nome_planta)`: zera o score, grava `ultima_rega = hoje`, insere linha em `historico_regas` com o score que a planta tinha antes de zerar (para dar visibilidade de quão atrasada estava).

## Automação e avisos

- Tarefa agendada do Claude, 1x/dia: para cada planta, busca clima da cidade configurada, recalcula o score (base + clima), grava em `historico_scores`, atualiza `plantas.score`.
- Se `score ≥ 100`: dispara notificação (push/e-mail via tarefas agendadas do Claude) listando as plantas que precisam de água.
- Não há flag de "já avisado hoje" separada — a notificação diária simplesmente lista todas as plantas com `score ≥ 100` no momento; se a planta não foi regada, ela aparece nos avisos seguintes automaticamente, com o score cada vez maior indicando o atraso.

## Estrutura de código

```
calculadora-rega/
  db.py            # conexão Turso, criação de tabelas, CRUD de plantas/histórico
  regras_score.py  # tabela de regras do incremento base por atributo
  clima.py         # geocoding + forecast do Open-Meteo, cálculo do incremento climático
  motor.py         # roda 1x/dia: calcula score de cada planta, decide quem avisar
  regar.py         # função regar(nome_planta)
  main.py          # ponto de entrada da tarefa agendada
  migracao.py      # script único: lê Bd_Plantas.ipynb e popula o Turso
  config.py        # cidade, credenciais do Turso (via variáveis de ambiente / .env, não versionado)
```

O notebook (`Bd_Plantas.ipynb`) deixa de ser a fonte de dados e passa a ser opcional, só para consulta/edição manual pontual.

## Fora de escopo (v1)

- Site ou app com interface própria (mencionado como possível evolução futura, não faz parte deste plano).
- Confirmação de rega via chat/notificação interativa (fica só a função `regar()` por enquanto).
- Autenticação multiusuário — assume-se um único usuário/uma única localização configurável por planta.

## Testes

- Testes unitários para `regras_score.py` (cada regra isolada) e para o cálculo do modificador climático em `clima.py` (dado um JSON de resposta simulado da API, o incremento calculado bate com o esperado).
- Teste de integração do `motor.py` com a API do Open-Meteo mockada (sem depender de rede) e um banco Turso de teste (ou SQLite local para os testes, já que o dialeto é compatível).
- Script de migração validado manualmente contra os dados reais do notebook.
