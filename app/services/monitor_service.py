"""
Monitor de entregas/devoluções — loop em background dos alertas proativos.

Espelha o padrão de `polling_service`: roda enquanto o servidor está ativo e, a
cada `ALERTAS_INTERVALO_SEGUNDOS`, dispara uma varredura. Erros de um ciclo são
logados e não derrubam o loop.
"""
import asyncio
import logging

from app.config import settings
from app.database import local
from app.services.notificacao_service import executar_varredura

logger = logging.getLogger(__name__)

_rodando = False


async def iniciar_monitor():
    """Loop principal. Chamado via asyncio.create_task no startup."""
    global _rodando
    if _rodando:
        return
    _rodando = True

    local.init_db()
    intervalo = settings.alertas_intervalo_segundos
    logger.info("Monitor de alertas ao vendedor iniciado (intervalo: %ds)", intervalo)

    while _rodando:
        try:
            await executar_varredura()
        except Exception as exc:  # cinto de segurança extra
            logger.error("Ciclo do monitor de alertas falhou: %s", exc)
        await asyncio.sleep(intervalo)


def parar_monitor():
    global _rodando
    _rodando = False
