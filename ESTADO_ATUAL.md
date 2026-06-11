# Estado atual — handoff para a sessão no servidor

> Leia este arquivo primeiro. Ele resume o que foi feito, o que falta e os
> comandos prontos (PowerShell/Windows). O histórico detalhado está nos commits
> da branch `feat/alertas-proativos-vendedor`.

## Branch

Trabalho em `feat/alertas-proativos-vendedor` (ainda **não** mesclada na `main`).
Inclui tudo: alertas proativos + correções do bot.

```powershell
git branch --show-current      # deve ser feat/alertas-proativos-vendedor
git log --oneline -1           # commit mais recente da feature
```

## Ambiente do servidor (fatos)

- **SO:** Windows, terminal **PowerShell** (NÃO use sintaxe bash; `curl` é alias
  de Invoke-WebRequest — prefira `Invoke-RestMethod`; `python3` não existe, é `python`).
- Projeto em `C:\Users\Administrator\Torre-de-Controle-DIA`, com `.venv` ativo.
- **torre-controle (FastAPI):** `uvicorn app.main:app --host 0.0.0.0 --port 8001`
- **Evolution API:** `npm start`, escuta em `http://localhost:8080`, instância
  `torre-controle`, apikey `DIA@torre2026`.
- ⚠️ **Conflito de porta resolvido:** Evolution fica na **8080**, torre-controle
  na **8001**. Nunca subir a torre-controle na 8080.

## O que foi construído (feature de alertas proativos)

Avisa um **grupo de WhatsApp** (supervisores/gerentes) quando um pedido é
ENTREGUE ou DEVOLVIDO. Decisões já tomadas:
- Destino = **um grupo único** (`ALERTAS_GRUPO_JID`), não números individuais.
- Telefone individual do vendedor **não** é usado (cadastro do PCUSUARI é ruim).
- Avisa de todos os pedidos; só remove o prefixo `OF ` (vendedor desligado) do
  nome exibido.
- Mensagem em formato de painel (vendedor/cliente/pedido/motivo).
- Dedup por `(numero_pedido, evento)` em SQLite local (`app/data/notificacoes.db`).

Arquivos principais:
- `app/services/notificacao_service.py` — varredura + montagem da mensagem
- `app/services/monitor_service.py` — loop em background (a cada 15 min)
- `app/database/local.py` — SQLite (dedup + log)
- `app/services/winthor_service.py::buscar_pedidos_finalizados()` — candidatos
- `app/routers/notificacoes.py` — `GET /notificacoes`, `POST /notificacoes/varredura`

Config no `.env` (já documentado em `.env.example`):
```
ALERTAS_VENDEDOR_ENABLED=false        # ligar quando validado
ALERTAS_INTERVALO_SEGUNDOS=900
ALERTAS_LOOKBACK_HORAS=6
ALERTAS_SQLITE_PATH=app/data/notificacoes.db
ALERTAS_GRUPO_JID=                     # JID do grupo (@g.us) — preencher
```

## Pendências (em ordem de prioridade)

### 1. Confirmar que o deploy pega (provável raiz de tudo)
No último teste, o log `WEBHOOK RAW` (adicionado ao webhook) **não apareceu**,
indicando que o uvicorn estava rodando **código antigo**. Antes de qualquer
diagnóstico: `git pull`, conferir `git log -1`, e **reiniciar o uvicorn** de fato
(Ctrl+C no processo e subir de novo). Sem isso, nada novo surte efeito.

### 2. Bot não responde quando mencionado no grupo
- DM pro bot funciona; mensagem no grupo não gera resposta.
- Já descartado: `groupsIgnore` da Evolution **está false** (não é isso).
- Pegadinha: o webhook só logava após extrair numero+texto, então mensagens de
  grupo descartadas pelo parser não apareciam no log. Por isso foi adicionado um
  log temporário `WEBHOOK RAW:` no início de `receber_mensagem`
  (`app/routers/whatsapp.py`).
- **Próximo passo:** com o código novo rodando, mencionar o bot no grupo e
  capturar a linha `WEBHOOK RAW:` correspondente. Com o payload real do grupo em
  mãos, corrigir o parser de menção em `_extrair_mensagem` (o bloco `if "@g.us"`).
  Hoje ele exige `extendedTextMessage.contextInfo.mentionedJid` — pode ser que a
  Evolution mande a menção em outra estrutura.
- ⚠️ Remover o log `WEBHOOK RAW` (e o log de "Webhook ignorado") depois de resolver.

### 3. Validar leitura de NF (corrigido, falta testar)
Commit `1cf1d06`: número solto agora tenta **pedido → NF → cliente** em cascata
(`app/routers/consulta.py::_resolver_ambiguo`). Antes, número sem prefixo era
sempre tratado como pedido e NF nunca era encontrada. Validar mandando um número
de NF conhecido em DM.

### 4. Ligar os alertas de devolução/entrega no grupo
Quando o grupo e os testes estiverem ok:
```
ALERTAS_GRUPO_JID=<jid@g.us>
ALERTAS_VENDEDOR_ENABLED=true
WHATSAPP_ENABLED=true
```
Reiniciar. Validar antes com `POST /notificacoes/varredura` e `WHATSAPP_ENABLED=false`.

### 5. (Recomendado) Segurança do `/discovery`
`app/routers/discovery.py` permite ler/dump de qualquer tabela do Oracle. Foi
feito como temporário. Proteger com token ou remover antes de uso definitivo.

### 6. (Operação) Persistir `app/data/` se rodar em Docker
O SQLite de dedup precisa sobreviver a redeploys; senão o grupo pode receber
alertas repetidos. (Hoje está rodando direto com uvicorn, não Docker.)

## Comandos prontos (PowerShell)

### Deploy / reiniciar
```powershell
cd C:\Users\Administrator\Torre-de-Controle-DIA
git pull
git log --oneline -1
# reiniciar o uvicorn no terminal dele: Ctrl+C, depois:
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### Evolution — ver config / grupos / webhook
```powershell
$h = @{ apikey = "DIA@torre2026" }
$base = "http://localhost:8080"

# settings da instância
Invoke-RestMethod -Uri "$base/settings/find/torre-controle" -Headers $h | ConvertTo-Json -Depth 10

# listar grupos (achar o JID @g.us)
Invoke-RestMethod -Uri "$base/group/fetchAllGroups/torre-controle?getParticipants=false" -Headers $h |
  Select-Object subject, id

# ver webhook configurado
Invoke-RestMethod -Uri "$base/webhook/find/torre-controle" -Headers $h | ConvertTo-Json -Depth 10
```

### torre-controle — testar
```powershell
# consulta direta (pedido / NF / cliente)
Invoke-RestMethod -Uri "http://localhost:8001/consulta?q=NUMERO" | ConvertTo-Json -Depth 10

# varredura de alertas (não envia se WHATSAPP_ENABLED=false)
Invoke-RestMethod -Uri "http://localhost:8001/notificacoes/varredura" -Method Post | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8001/notificacoes" | ConvertTo-Json -Depth 10

# rodar os testes
python -m pytest -q
```

## Frase de partida sugerida para a sessão no servidor

> "Leia ESTADO_ATUAL.md. Estamos na branch feat/alertas-proativos-vendedor.
> Prioridade: (1) garantir que o código novo está rodando; (2) capturar o
> WEBHOOK RAW de uma mensagem de grupo e corrigir o parser de menção;
> (3) validar leitura de NF; (4) ligar os alertas no grupo."
