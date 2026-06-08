"""
Roteador WhatsApp.

GET  /whatsapp/webhook  — verificação do webhook (Meta/WhatsApp)
POST /whatsapp/webhook  — recebe mensagens e responde automaticamente
POST /whatsapp/testar   — envia mensagem de teste sem webhook (desenvolvimento)
"""
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.routers.consulta import consulta_livre
from app.services.whatsapp_service import enviar_mensagem

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])
logger = logging.getLogger(__name__)


# ── Verificação do webhook (handshake Meta) ───────────────────────────────────

@router.get("/webhook", summary="Verificação do webhook WhatsApp")
def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta/WhatsApp chama este endpoint para verificar a URL do webhook.
    Retorna hub.challenge se o token bater.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("Webhook WhatsApp verificado com sucesso.")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token de verificação inválido.")


# ── Recebimento de mensagens ──────────────────────────────────────────────────

@router.post("/webhook", summary="Recebe mensagens do WhatsApp e responde")
async def receber_mensagem(request: Request):
    """
    Recebe o payload do WhatsApp, extrai a mensagem de texto,
    consulta o status do pedido e responde automaticamente.

    Suporta o formato padrão da Cloud API (Meta) e formato genérico.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido.")

    # Extrai número e texto — suporta formato Meta Cloud API
    numero, texto = _extrair_mensagem(body)

    if not numero or not texto:
        logger.debug("Mensagem recebida sem número ou texto válidos.")
        return {"status": "ignorado"}

    logger.info("Mensagem recebida de %s: %s", numero, texto)

    try:
        status = await consulta_livre(q=texto)
        resposta = status.resposta_formatada or status.descricao
    except Exception as exc:
        logger.error("Erro ao consultar status: %s", exc)
        resposta = (
            "Não consegui localizar as informações. "
            "Por favor, informe o número do pedido ou NF."
        )

    await enviar_mensagem(numero, resposta)
    return {"status": "respondido", "para": numero}


def _extrair_mensagem(body: dict) -> tuple[str | None, str | None]:
    """
    Extrai (numero, texto) do payload.
    Suporta Evolution API v2 e Meta Cloud API.
    """
    # ── Evolution API v2 ──────────────────────────────────────────────────────
    # Formato: {"event": "messages.upsert", "data": {"key": {"remoteJid": ...}, "message": {...}}}
    try:
        evento = body.get("event", "")
        if "message" in evento:
            data = body["data"]
            # Ignora mensagens enviadas pelo próprio bot
            if data["key"].get("fromMe"):
                return None, None
            jid = data["key"]["remoteJid"]
            # Remove sufixo @s.whatsapp.net ou @g.us (grupos — ignorar)
            if "@g.us" in jid:
                return None, None
            numero = jid.replace("@s.whatsapp.net", "").replace("@c.us", "")
            msg = data.get("message", {})
            texto = (
                msg.get("conversation")
                or msg.get("extendedTextMessage", {}).get("text")
                or msg.get("imageMessage", {}).get("caption")
                or ""
            ).strip()
            return numero, texto or None
    except (KeyError, TypeError):
        pass

    # ── Meta Cloud API ────────────────────────────────────────────────────────
    try:
        entry = body["entry"][0]
        change = entry["changes"][0]["value"]
        msg = change["messages"][0]
        numero = msg["from"]
        texto = msg.get("text", {}).get("body", "").strip()
        return numero, texto or None
    except (KeyError, IndexError, TypeError):
        pass

    # ── Fallback genérico ─────────────────────────────────────────────────────
    numero = body.get("from") or body.get("numero") or body.get("phone")
    texto = body.get("message") or body.get("text") or body.get("body")
    return numero, texto


# ── Teste manual ─────────────────────────────────────────────────────────────

class TestePayload(BaseModel):
    numero: str
    mensagem: str


@router.post("/testar", summary="Envia mensagem de teste manualmente")
async def testar_mensagem(payload: TestePayload):
    resultado = await enviar_mensagem(payload.numero, payload.mensagem)
    return resultado
