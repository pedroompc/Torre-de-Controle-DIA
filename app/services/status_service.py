"""
Motor de status unificado.
Combina dados do Winthor + Fusion e calcula o status consolidado do pedido.
"""
import logging
from typing import Optional

from app.schemas.status import (
    DadosWinthor, DadosDevolucao, DadosFusion,
    StatusPedido, StatusUnificado, STATUS_DESCRICAO,
)

logger = logging.getLogger(__name__)


def calcular_status(
    winthor: Optional[DadosWinthor],
    devolucao: Optional[DadosDevolucao],
    fusion: Optional[DadosFusion],
) -> StatusUnificado:
    """
    Hierarquia de decisão (Fusion tem prioridade sobre Winthor para status pós-saída):
      1. Pedido não encontrado no Winthor → NAO_ENCONTRADO
      2. Fusion: DEVOLVIDO ou DEVOLUCAO_PARCIAL → DEVOLVIDO
      3. Fusion: ENTREGUE → ENTREGUE
      4. Fusion: ADIADO → EM_ROTA (ainda em campo)
      5. Fusion: EM_ROTA / MOTORISTA_NO_CLIENTE / ENTREGA_EM_ANDAMENTO → EM_ROTA
      6. Sem dados Fusion mas carga saiu → EM_ROTA
      7. Nota emitida mas sem carga → FATURADO
      8. Pedido Liberado/Montado → EM_SEPARACAO
    """
    if winthor is None:
        return StatusUnificado.NAO_ENCONTRADO

    if fusion and fusion.integrado and fusion.status_entrega:
        s = fusion.status_entrega
        if s in ("DEVOLVIDO", "DEVOLUCAO_PARCIAL"):
            return StatusUnificado.DEVOLVIDO
        if s == "ENTREGUE":
            return StatusUnificado.ENTREGUE
        if s in ("EM_ROTA", "MOTORISTA_NO_CLIENTE", "ENTREGA_EM_ANDAMENTO", "ADIADO", "AGUARDANDO"):
            return StatusUnificado.EM_ROTA

    # Fallback: dados apenas do Winthor
    if winthor.data_saida_carga:
        return StatusUnificado.EM_ROTA
    if winthor.numero_nota:
        return StatusUnificado.FATURADO
    if winthor.status_pedido in ("L", "M"):
        return StatusUnificado.EM_SEPARACAO
    if winthor.status_pedido == "F":
        return StatusUnificado.FATURADO

    return StatusUnificado.EXCECAO


def montar_status_pedido(
    winthor: Optional[DadosWinthor],
    devolucao: Optional[DadosDevolucao],
    fusion: Optional[DadosFusion],
    resposta_formatada: Optional[str] = None,
) -> StatusPedido:
    status = calcular_status(winthor, devolucao, fusion)
    return StatusPedido(
        numero_pedido=winthor.numero_pedido if winthor else None,
        status=status,
        descricao=STATUS_DESCRICAO[status],
        winthor=winthor,
        devolucao=devolucao,
        fusion=fusion,
        resposta_formatada=resposta_formatada,
    )
