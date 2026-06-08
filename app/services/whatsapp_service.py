"""
Serviço WhatsApp — envio de mensagens via API HTTP.
Baseado no monitor-winthor. WHATSAPP_ENABLED=false por padrão.
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def enviar_mensagem(numero: str, mensagem: str) -> dict:
    """
    Envia mensagem de texto para um número via API WhatsApp.
    Quando WHATSAPP_ENABLED=false, apenas loga e retorna sem enviar.
    """
    if not settings.whatsapp_enabled:
        logger.info(
            "WhatsApp desativado. Mensagem NÃO enviada para %s.", numero
        )
        logger.debug("Conteúdo simulado:\n%s", mensagem)
        return {"enviado": False, "detalhe": "WhatsApp desativado."}

    if not settings.whatsapp_api_url:
        logger.error("WHATSAPP_API_URL não configurada.")
        return {"enviado": False, "detalhe": "URL da API não configurada."}

    # Evolution API v2: usa "number" e "text", autenticação via "apikey"
    # Para grupos, "number" recebe o JID completo (ex: 558199...@g.us)
    payload = {"number": numero, "text": mensagem}
    headers = {
        "apikey": settings.whatsapp_api_token,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.whatsapp_timeout_seconds) as client:
            r = await client.post(settings.whatsapp_api_url, json=payload, headers=headers)
            r.raise_for_status()
            logger.info("Mensagem enviada com sucesso para %s.", numero)
            return {"enviado": True, "detalhe": "Mensagem enviada."}
    except httpx.TimeoutException:
        logger.error("Timeout ao enviar WhatsApp para %s.", numero)
        return {"enviado": False, "detalhe": "Timeout na API."}
    except httpx.HTTPStatusError as exc:
        logger.error("Erro HTTP %d ao enviar WhatsApp.", exc.response.status_code)
        return {"enviado": False, "detalhe": f"Erro HTTP {exc.response.status_code}."}
    except Exception as exc:
        logger.error("Erro inesperado WhatsApp: %s", exc)
        return {"enviado": False, "detalhe": str(exc)}
