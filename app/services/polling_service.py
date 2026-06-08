"""
Polling do Evolution API — busca mensagens novas a cada 3 segundos.
Alternativa ao webhook para casos onde o webhook não dispara.

Fluxo:
  1. A cada 3s, busca as últimas mensagens da instância
  2. Filtra mensagens não processadas (fromMe=false, novas)
  3. Para cada nova mensagem, consulta o status e responde
"""
import asyncio
import logging
import time
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# IDs de mensagens já processadas (evita duplicatas)
_processados: set[str] = set()
# Timestamp da última verificação (só busca mensagens mais recentes)
_ultimo_timestamp: int = int(time.time()) - 10

_rodando = False


async def _buscar_mensagens() -> list[dict]:
    """Busca as últimas mensagens recebidas no Evolution API."""
    global _ultimo_timestamp

    url = f"{settings.evolution_api_url}/chat/findMessages/torre-controle"
    headers = {"apikey": settings.evolution_api_key}
    payload = {
        "where": {
            "key": {"fromMe": False},
            "messageTimestamp": {"gte": _ultimo_timestamp}
        },
        "limit": 20
    }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                data = r.json()
                # Atualiza timestamp para próxima busca
                _ultimo_timestamp = int(time.time()) - 5
                return data if isinstance(data, list) else data.get("messages", [])
    except Exception as exc:
        logger.debug("Erro ao buscar mensagens: %s", exc)

    return []


async def _processar_mensagem(msg: dict):
    """Processa uma mensagem e envia resposta."""
    # Importa aqui para evitar circular imports
    from app.routers.consulta import consulta_livre
    from app.services.whatsapp_service import enviar_mensagem

    try:
        msg_id = msg.get("key", {}).get("id", "")
        if not msg_id or msg_id in _processados:
            return

        # Ignora grupos
        jid = msg.get("key", {}).get("remoteJid", "")
        if "@g.us" in jid:
            return

        # Extrai número e texto
        numero = jid.replace("@s.whatsapp.net", "").replace("@c.us", "")
        message_content = msg.get("message", {})
        texto = (
            message_content.get("conversation")
            or message_content.get("extendedTextMessage", {}).get("text")
            or ""
        ).strip()

        if not texto or not numero:
            return

        logger.info("Nova mensagem de %s: %s", numero, texto)
        _processados.add(msg_id)

        # Limpa set se ficou muito grande
        if len(_processados) > 1000:
            _processados.clear()

        # Consulta status e responde
        status = await consulta_livre(q=texto)
        resposta = status.resposta_formatada or status.descricao
        await enviar_mensagem(numero, resposta)

    except Exception as exc:
        logger.error("Erro ao processar mensagem: %s", exc)


async def iniciar_polling():
    """Loop de polling — roda em background enquanto o servidor está ativo."""
    global _rodando

    if _rodando:
        return
    _rodando = True

    logger.info("Polling do WhatsApp iniciado (intervalo: 3s)")

    while _rodando:
        try:
            mensagens = await _buscar_mensagens()
            for msg in mensagens:
                await _processar_mensagem(msg)
        except Exception as exc:
            logger.debug("Ciclo de polling: %s", exc)

        await asyncio.sleep(3)


def parar_polling():
    global _rodando
    _rodando = False
