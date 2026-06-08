"""
Roteador de alertas para a equipe de monitoramento.

GET /alertas         — lista todos os alertas ativos agora
GET /alertas/resumo  — contagem por tipo e severidade
"""
import logging
from collections import Counter

from fastapi import APIRouter

from app.schemas.alerta import Alerta
from app.services.alert_service import gerar_todos_alertas

router = APIRouter(prefix="/alertas", tags=["Alertas"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[Alerta], summary="Lista todos os alertas ativos")
def listar_alertas():
    return gerar_todos_alertas()


@router.get("/resumo", summary="Resumo de alertas por tipo e severidade")
def resumo_alertas():
    alertas = gerar_todos_alertas()
    por_tipo = Counter(a.tipo.value for a in alertas)
    por_severidade = Counter(a.severidade.value for a in alertas)
    return {
        "total": len(alertas),
        "por_severidade": dict(por_severidade),
        "por_tipo": dict(por_tipo),
    }
