"""
Serviço de alertas — gera a fila de exceções para o monitoramento.
Consulta Winthor e monta os alertas conforme as regras de negócio.
"""
import logging
from datetime import datetime

from app.config import settings
from app.schemas.alerta import Alerta, TipoAlerta, ALERTA_CONFIG
from app.services import winthor_service

logger = logging.getLogger(__name__)


def gerar_todos_alertas() -> list[Alerta]:
    """
    Executa todas as verificações de alerta e retorna a lista consolidada.
    Chamado pelo endpoint GET /alertas ou por um job periódico.
    """
    alertas: list[Alerta] = []

    alertas += _alertas_sem_fatura()
    alertas += _alertas_faturado_sem_carga()

    # Ordenar por severidade: ALTA → MEDIA → BAIXA
    ordem = {"ALTA": 0, "MEDIA": 1, "BAIXA": 2}
    alertas.sort(key=lambda a: ordem.get(a.severidade.value, 9))

    logger.info("Total de alertas gerados: %d", len(alertas))
    return alertas


def _alertas_sem_fatura() -> list[Alerta]:
    """Pedidos liberados/montados sem faturamento acima do limite de horas."""
    try:
        rows = winthor_service.buscar_alertas_sem_fatura(
            settings.alerta_horas_sem_fatura
        )
    except Exception as exc:
        logger.error("Erro ao buscar alertas sem fatura: %s", exc)
        return []

    config = ALERTA_CONFIG[TipoAlerta.LIBERADO_SEM_FATURA]
    return [
        Alerta(
            tipo=TipoAlerta.LIBERADO_SEM_FATURA,
            severidade=config["severidade"],
            acao_sugerida=config["acao"],
            numero_pedido=r.get("numero_pedido"),
            nome_cliente=r.get("nome_cliente"),
            nome_rca=r.get("nome_rca"),
            detalhe=(
                f"Pedido {r.get('numero_pedido')} liberado há "
                f"{r.get('horas_parado', 0):.0f}h sem faturamento."
            ),
            gerado_em=datetime.now(),
        )
        for r in rows
    ]


def _alertas_faturado_sem_carga() -> list[Alerta]:
    """Notas emitidas mas sem carga vinculada acima do limite de horas."""
    try:
        rows = winthor_service.buscar_alertas_faturado_sem_carga(
            settings.alerta_horas_faturado_sem_carga
        )
    except Exception as exc:
        logger.error("Erro ao buscar alertas faturado sem carga: %s", exc)
        return []

    config = ALERTA_CONFIG[TipoAlerta.FATURADO_SEM_CARGA]
    return [
        Alerta(
            tipo=TipoAlerta.FATURADO_SEM_CARGA,
            severidade=config["severidade"],
            acao_sugerida=config["acao"],
            numero_pedido=r.get("numero_pedido"),
            numero_nota=r.get("numero_nota"),
            nome_cliente=r.get("nome_cliente"),
            nome_rca=r.get("nome_rca"),
            detalhe=(
                f"NF {r.get('numero_nota')} faturada há "
                f"{r.get('horas_sem_carga', 0):.0f}h sem saída de carga."
            ),
            gerado_em=datetime.now(),
        )
        for r in rows
    ]
