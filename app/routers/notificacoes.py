"""
Roteador de notificações proativas ao vendedor.

GET  /notificacoes            — histórico de notificações enviadas (SQLite)
POST /notificacoes/varredura  — roda 1 ciclo de varredura na hora (teste/manual)

Sem autenticação: o projeto ainda não tem padrão de auth e os endpoints são
abertos. Mantido em router próprio para facilitar proteger depois (ex.: aplicar
uma dependência de API key só neste APIRouter).
"""
import logging

from fastapi import APIRouter, Query

from app.database import local
from app.services.notificacao_service import executar_varredura

router = APIRouter(prefix="/notificacoes", tags=["Notificações"])
logger = logging.getLogger(__name__)


@router.get("", summary="Histórico de notificações enviadas ao vendedor")
def listar(limit: int = Query(50, ge=1, le=500)):
    return {"notificacoes": local.listar_notificacoes(limit=limit)}


@router.post("/varredura", summary="Executa uma varredura de alertas agora")
async def varredura():
    """
    Dispara um ciclo imediato. Com WHATSAPP_ENABLED=false, apenas loga as
    mensagens que seriam enviadas e popula o SQLite — útil para testar com
    dados reais sem incomodar o vendedor.
    """
    return await executar_varredura()
