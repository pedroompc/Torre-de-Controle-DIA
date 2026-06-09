# Spec — Alertas proativos ao vendedor

Data: 2026-06-09
Projeto: torre-controle

## Objetivo

Avisar o vendedor automaticamente, via WhatsApp, quando um pedido de um cliente
dele for **ENTREGUE** ou **DEVOLVIDO**, sem que ele precise consultar o bot.

Mensagens esperadas:

- Entregue: `Olá, {vendedor}. O pedido {numero} do cliente {cliente} foi entregue com sucesso.`
- Devolvido: `Olá, {vendedor}. Atenção: o pedido {numero} do cliente {cliente} foi devolvido.`

Quando houver dados adicionais (data de entrega, motorista, motivo da devolução),
incluir de forma objetiva.

## Contexto do projeto (estado atual)

- FastAPI + Python 3.12. Oracle (Winthor + schema FUSIONT) **somente leitura**
  (bloqueio anti-DML por regex em `app/database/oracle.py`).
- Status do pedido é calculado on-demand em `app/services/status_service.py`
  cruzando Winthor + Fusion. Não há histórico/evento de mudança de status.
- Pedidos não são persistidos localmente; tudo é consultado no Oracle.
- Vendedor identificado por `PCPEDC.CODUSUR` → `PCUSUARI.NOME`. Telefone do
  vendedor **não** é buscado hoje.
- Envio WhatsApp: `app/services/whatsapp_service.enviar_mensagem(numero, texto)`
  (Evolution API), com flag `WHATSAPP_ENABLED` e tratamento de erro/timeout.
- Existe `app/services/polling_service.py` (loop asyncio) como padrão de
  background, atualmente desativado. `alert_service.py` gera fila de exceções
  do monitoramento sob demanda em `GET /alertas` (propósito diferente desta feature).
- Não há banco local, tabela de notificações, nem job periódico rodando.
- Não há padrão de autenticação: todos os endpoints são abertos.

## Decisões aprovadas

1. **Telefone do vendedor**: lido de `PCUSUARI.TELCELULAR` (confirmar nome exato
   via `GET /discovery/colunas/PCUSUARI`), com normalização para o formato da
   Evolution API (`55` + DDD + número). Telefone vazio/inválido → registra
   `falha` no SQLite e o ciclo segue.
2. **Fusion** já está conectado a dados reais → detectamos ENTREGUE (evento `7`)
   e DEVOLVIDO (`9`/`10`) via Fusion, além de devolução via Winthor (`PCNFENT`).
3. **Varredura** a cada 15 min (`ALERTAS_INTERVALO_SEGUNDOS=900`), com lookback
   maior que o intervalo (`ALERTAS_LOOKBACK_HORAS=6`) porque o dedup protege
   contra repetição.
4. Endpoints `/notificacoes` ficam **abertos** (não há auth no projeto), mas
   isolados em router próprio para facilitar proteção futura.

## Arquitetura

Caminho paralelo, sem alterar o fluxo de consulta existente. Loop asyncio em
background (padrão do `polling_service`), iniciado no `startup` se a flag estiver
ligada:

```
a cada N seg → monitor_service.loop
  1. winthor_service.buscar_pedidos_finalizados(lookback)  → set de NUMPED candidatos
  2. para cada NUMPED: consulta._resolver_pedido(NUMPED)   → status unificado real
  3. status ∈ {ENTREGUE, DEVOLVIDO}?  (senão pula)
  4. local.ja_notificado(NUMPED, evento) com sucesso?  (se sim pula)
  5. resolve telefone do vendedor (PCUSUARI, normalizado)
  6. monta mensagem curta
  7. whatsapp_service.enviar_mensagem(...)
  8. local.registrar_notificacao(... status_envio sucesso|falha ...)
```

Reusa `_resolver_pedido` para que a regra de status (incl. prioridade
devolução > entrega) viva num lugar só. O monitor apenas descobre candidatos e
decide notificar.

## Arquivos

### Criar
- `app/database/local.py` — SQLite: `init_db()`, `ja_notificado(pedido, evento) -> bool`,
  `registrar_notificacao(...)`, `listar_notificacoes(limit)`.
- `app/services/notificacao_service.py` — `executar_varredura() -> dict` (1 ciclo:
  candidatos → dedup → telefone → mensagem → envio → log); funções puras
  `normalizar_telefone(raw) -> Optional[str]` e `montar_mensagem(status) -> str`.
- `app/services/monitor_service.py` — `iniciar_monitor()` / `parar_monitor()`
  (loop asyncio que chama `executar_varredura` a cada intervalo).
- `app/routers/notificacoes.py` — `GET /notificacoes` (histórico) e
  `POST /notificacoes/varredura` (roda 1 ciclo na hora; útil para teste).
- `tests/test_notificacao.py` — testes de `normalizar_telefone`, `montar_mensagem`
  e dedup (SQLite em arquivo temporário).

### Alterar
- `app/schemas/status.py` — `DadosWinthor.telefone_rca: Optional[str] = None`.
- `app/services/winthor_service.py` — (a) `usu.TELCELULAR AS telefone_rca` nas 3
  queries de pedido; (b) nova função `buscar_pedidos_finalizados(lookback_horas)`.
- `app/config.py` + `.env.example` — novas flags.
- `app/main.py` — incluir router `notificacoes`; no `startup`,
  `asyncio.create_task(iniciar_monitor())` se `ALERTAS_VENDEDOR_ENABLED`.

## Persistência (SQLite local)

`app/data/notificacoes.db` (Oracle continua read-only e intocado).

```sql
CREATE TABLE IF NOT EXISTS notificacoes_enviadas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_pedido INTEGER NOT NULL,
    evento        TEXT    NOT NULL,         -- 'ENTREGUE' | 'DEVOLVIDO'
    codigo_rca    INTEGER,
    nome_rca      TEXT,
    telefone      TEXT,
    nome_cliente  TEXT,
    mensagem      TEXT,
    status_envio  TEXT    NOT NULL,         -- 'sucesso' | 'falha'
    detalhe       TEXT,
    criado_em     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_notif_pedido_evento
    ON notificacoes_enviadas (numero_pedido, evento);
```

## Deduplicação

Chave = `(numero_pedido, evento)`. Antes de enviar, verifica se já existe linha
com `status_envio='sucesso'` para a chave; se sim, pula. Sem `UNIQUE`: falhas
são re-tentadas no ciclo seguinte e, ao ter sucesso, nunca mais repetem. A chave
inclui o evento, então "entregue" e depois "devolvido" do mesmo pedido geram
dois alertas distintos (correto).

## Detecção de candidatos (`buscar_pedidos_finalizados`)

Duas fontes, unificadas num conjunto de NUMPEDs:

1. **Fusion**: `FUSIONT.FUSIONTRAK_INT_EVENTOS` com `TIPO IN ('7','9','10')` e
   `DATAHORA >= SYSDATE - lookback/24`. Mapeia `CARGA_FORMADA_ERP` +
   `CLIENTE_CODIGO_ERP` de volta para `PCNFSAID`/`PCPEDC` → `NUMPED`.
2. **Winthor (devolução)**: `PCNFENT` recente (`DTENT >= SYSDATE - lookback/24`)
   pelo caminho já validado (`PCNFENT → PCESTCOM → PCNFSAID → NUMPED`), com os
   mesmos filtros de CFOP/tipo de descarga usados em `_SQL_DEVOLUCAO`.

A confirmação final do status (ENTREGUE/DEVOLVIDO) é feita por `_resolver_pedido`,
não pela query de candidatos.

## Mensagem ao vendedor

- Base conforme exemplos do objetivo.
- Extras objetivos quando disponíveis: data de entrega (Fusion `data_evento`),
  motorista (`winthor.nome_motorista`), motivo da devolução
  (`fusion.desc_devolucao`/`motivo_devolucao` ou `devolucao.observacao`).

## Tratamento de falhas

- Erro Oracle/Fusion na varredura → `try/except` por ciclo, loga e segue
  (não derruba o loop).
- Telefone inválido → registra `falha` ("telefone inválido"), não envia, segue.
- Falha no envio → `enviar_mensagem` retorna `{"enviado": False}`; grava `falha`
  e o pedido é re-tentado no próximo ciclo.
- `ALERTAS_VENDEDOR_ENABLED=false` desliga o monitor sem remover código.

## Logs

Cada tentativa vira linha no SQLite **e** linha no log de arquivo existente
(`app/logs/torre-controle.log`) via `logging` padrão. `GET /notificacoes`
expõe o histórico.

## Configuração nova (.env)

```
ALERTAS_VENDEDOR_ENABLED=false
ALERTAS_INTERVALO_SEGUNDOS=900
ALERTAS_LOOKBACK_HORAS=6
ALERTAS_SQLITE_PATH=app/data/notificacoes.db
```

## Testes

1. `tests/test_notificacao.py` (pytest): normalização de telefone, montagem da
   mensagem (entregue/devolvido), dedup com SQLite temporário.
2. `POST /notificacoes/varredura` com `WHATSAPP_ENABLED=false`: roda ciclo real
   de leitura, só loga a mensagem, popula SQLite — valida com dados reais sem
   incomodar vendedor.
3. `GET /notificacoes`: inspeciona histórico.
4. Fim-a-fim controlado: `WHATSAPP_ENABLED=true` para número de teste próprio.

## Pendências externas (não bloqueiam o código)

- Confirmar coluna real de telefone em `PCUSUARI` e formato gravado.
- Confirmar confiabilidade de `DATAHORA` nos eventos Fusion `7/9/10`.
