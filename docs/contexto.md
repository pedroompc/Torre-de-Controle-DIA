# Contexto do Projeto — torre-controle

## Objetivo

Central Inteligente de Entregas e Devoluções (Torre de Controle Logística).
Integra Winthor (Oracle) + Fusion (roteirizador) para gerar um status único e
confiável de cada pedido, respondendo automaticamente a vendedores via WhatsApp
ou portal web, e gerando alertas proativos para a equipe de monitoramento.

---

## Stack

| Componente       | Tecnologia                              |
|------------------|-----------------------------------------|
| Linguagem        | Python 3.12                             |
| Framework web    | FastAPI + Uvicorn                       |
| Banco Winthor    | Oracle — driver `oracledb` (somente leitura) |
| IA               | Claude API (Anthropic) via HTTPX        |
| WhatsApp         | API HTTP genérica / Meta Cloud API      |
| Templates        | Jinja2 (portal web)                     |

---

## Estrutura

```
torre-controle/
  app/
    main.py                   # entrypoint FastAPI + portal web
    config.py                 # configurações via pydantic-settings
    database/oracle.py        # conexão Oracle (somente SELECT)
    schemas/
      status.py               # StatusPedido, StatusUnificado, DadosWinthor...
      alerta.py               # Alerta, TipoAlerta, SeveridadeAlerta
    services/
      winthor_service.py      # queries Oracle — busca por pedido/NF/cliente
      fusion_service.py       # integração Fusion (MOCK até mapeamento)
      status_service.py       # motor de status unificado (Winthor + Fusion)
      ai_service.py           # Claude API — parser + formatação + classificação
      whatsapp_service.py     # envio de mensagens WhatsApp
      alert_service.py        # geração de alertas para o monitoramento
      notificacao_service.py  # alertas proativos ao vendedor (entrega/devolução)
      monitor_service.py      # loop em background que dispara a varredura
    database/local.py         # SQLite local — dedup + log das notificações
    routers/
      consulta.py             # GET /consulta — consulta por pedido/NF/cliente
      alertas.py              # GET /alertas — fila de exceções
      whatsapp.py             # POST /whatsapp/webhook — bot WhatsApp
      notificacoes.py         # GET /notificacoes — histórico + varredura manual
    templates/index.html      # portal web do vendedor
    static/css/style.css
    logs/
  docs/contexto.md
  requirements.txt
  .env.example
```

---

## Endpoints

| Método | Rota                        | Uso                                         |
|--------|-----------------------------|---------------------------------------------|
| GET    | `/`                         | Portal web (vendedor digita pedido/NF)      |
| GET    | `/health`                   | Health check da aplicação                  |
| GET    | `/health/oracle`            | Testa conexão com Oracle Winthor           |
| GET    | `/consulta?q=...`           | Consulta livre com parser IA               |
| GET    | `/consulta/pedido/{num}`    | Consulta direta por número do pedido       |
| GET    | `/consulta/nota/{num}`      | Consulta direta por número da NF           |
| GET    | `/consulta/cliente/{cod}`   | Últimos pedidos de um cliente              |
| GET    | `/alertas`                  | Fila de exceções para o monitoramento      |
| GET    | `/alertas/resumo`           | Contagem de alertas por tipo               |
| GET    | `/whatsapp/webhook`         | Verificação do webhook (Meta handshake)    |
| POST   | `/whatsapp/webhook`         | Recebe mensagens e responde automaticamente|
| POST   | `/whatsapp/testar`          | Envia mensagem de teste manualmente        |
| GET    | `/notificacoes`             | Histórico de alertas proativos enviados    |
| POST   | `/notificacoes/varredura`   | Roda uma varredura de entrega/devolução agora |

---

## Status Unificado do Pedido

| Status             | Condição                                               |
|--------------------|--------------------------------------------------------|
| EM_SEPARACAO       | PCPEDC.POSICAO = L ou M, sem NF emitida               |
| FATURADO           | NF emitida, sem saída de carga ainda                  |
| EM_ROTA            | Carga saiu (PCCARREG.DTSAIDA preenchida)              |
| ENTREGUE           | Confirmado pelo Fusion                                 |
| DEVOLVIDO          | PCNFENT registrada (devolução no Winthor)             |
| RECUSADO           | Recusa registrada no Fusion                            |
| EXCECAO            | Divergência entre sistemas                             |
| NAO_ENCONTRADO     | Pedido não localizado                                  |

---

## Tabelas Oracle Utilizadas

| Tabela    | Uso                                          |
|-----------|----------------------------------------------|
| PCPEDC    | Cabeçalho do pedido (status, datas, valor)   |
| PCCLIENT  | Cliente (nome, cidade, UF)                   |
| PCUSUARI  | Vendedor (RCA)                               |
| PCNFSAID  | Nota fiscal de saída (faturamento, carga)    |
| PCCARREG  | Carregamento (motorista, data saída)         |
| PCEMPR    | Colaboradores (nome do motorista)            |
| PCNFENT   | Nota de entrada de devolução                 |
| PCESTCOM  | Estatísticas comerciais (vínculo venda→dev.) |

---

## Integração Fusion

**SITUAÇÃO ATUAL:** Mock — retorna `None` (como se não houvesse dados do Fusion).

Quando o TI mapear o acesso ao Fusion, editar `app/services/fusion_service.py`:
- **API REST:** implementar chamada HTTPX com token/URL do .env
- **Banco de dados:** criar `app/database/fusion_db.py` com o driver correto

Setar `FUSION_ENABLED=true` no `.env` após implementar.

---

## Alertas Proativos (grupo de supervisores)

Avisa automaticamente um **grupo de WhatsApp** (supervisores/gerentes) quando um
pedido é **ENTREGUE** ou **DEVOLVIDO**. Os supervisores repassam aos seus
vendedores. Não há disparo para números individuais.

**Como funciona:** um loop em background (`monitor_service`) roda a cada
`ALERTAS_INTERVALO_SEGUNDOS`. A cada ciclo (`notificacao_service.executar_varredura`):

1. `winthor_service.buscar_pedidos_finalizados()` acha pedidos com evento
   finalizador recente (Fusion tipo 7/9/10 + devoluções recentes no `PCNFENT`).
2. Para cada candidato, o status real é confirmado por `consulta._resolver_pedido`
   (mesma regra de status da consulta — não há duplicação de lógica).
3. Deduplica via SQLite (`app/database/local.py`): não reenvia para o mesmo
   `(numero_pedido, evento)` já enviado com sucesso; falhas são re-tentadas.
4. Monta a mensagem (formato de painel, nomeando vendedor/cliente/pedido; o
   prefixo `OF ` de vendedores desligados é removido do nome exibido) e dispara
   para o grupo `ALERTAS_GRUPO_JID`.
5. Registra o resultado (sucesso/falha) no SQLite.

**Ligar:** definir `ALERTAS_GRUPO_JID` e `ALERTAS_VENDEDOR_ENABLED=true` no `.env`.
Antes disso, validar com `POST /notificacoes/varredura` (com `WHATSAPP_ENABLED=false`
apenas loga e popula o SQLite, sem disparar). Histórico em `GET /notificacoes`.

**Como obter o JID do grupo (Evolution API):**
`GET {EVOLUTION_API_URL}/group/fetchAllGroups/torre-controle?getParticipants=false`
(header `apikey`). Procure o grupo desejado e copie o campo `id` (termina em `@g.us`).

**Dependência confirmada em produção:** `DATAHORA` nos eventos Fusion (base da
janela de lookback).

---

## Configuração — Passos para Subir

```bash
# 1. Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Configurar variáveis
cp .env.example .env
# Editar .env com credenciais Oracle, API Key Claude, etc.

# 4. Subir o servidor
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 5. Acessar
# Portal web:   http://localhost:8001
# Docs API:     http://localhost:8001/docs
# Health:       http://localhost:8001/health
```

---

## Status Atual (Junho 2026)

| Item                                    | Status           |
|-----------------------------------------|------------------|
| Estrutura do projeto criada             | Concluído        |
| Conexão Oracle Winthor                  | Implementado     |
| Queries de status por pedido/NF/cliente | Implementado     |
| Detecção de devoluções (PCNFENT)        | Implementado     |
| Motor de status unificado               | Implementado     |
| Integração Claude API (IA)              | Implementado     |
| Portal web para vendedores              | Implementado     |
| Bot WhatsApp (webhook)                  | Implementado     |
| Alertas: liberado sem fatura            | Implementado     |
| Alertas: faturado sem carga             | Implementado     |
| Alertas proativos ao vendedor (entrega/devolução) | Implementado |
| Integração Fusion                       | **PENDENTE** (mock) |
| Implantação em servidor interno         | Pendente         |
| Testes com dados reais                  | Pendente         |

---

## Próximos Passos

1. Confirmar com TI o tipo de acesso ao Fusion (API ou banco)
2. Implementar `fusion_service.py` com acesso real
3. Configurar `.env` com credenciais Oracle e API Key Claude
4. Subir em servidor interno (porta não exposta à internet)
5. Testar consultas com pedidos reais do Winthor
6. Ativar WhatsApp com número de teste
7. Piloto com 3 a 5 vendedores
