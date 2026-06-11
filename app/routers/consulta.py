"""
Roteador de consulta de status do pedido.

GET /consulta?q=<numero_pedido|numero_nota|codigo_cliente>
  Parâmetro livre — a IA detecta o tipo automaticamente.

GET /consulta/pedido/{numero}
GET /consulta/nota/{numero}
GET /consulta/cliente/{codigo}
  Endpoints diretos sem IA (mais rápidos, para integração técnica).
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas.status import StatusPedido, StatusUnificado, STATUS_DESCRICAO
from app.services import winthor_service, fusion_service, ai_service
from app.services.status_service import montar_status_pedido

router = APIRouter(prefix="/consulta", tags=["Consulta"])
logger = logging.getLogger(__name__)


async def _resolver_pedido(numero_pedido: int) -> StatusPedido:
    """Busca Winthor + FusionTrak + devolução e monta o status unificado."""
    winthor = winthor_service.buscar_por_pedido(numero_pedido)
    if not winthor:
        return StatusPedido(
            status=StatusUnificado.NAO_ENCONTRADO,
            descricao=STATUS_DESCRICAO[StatusUnificado.NAO_ENCONTRADO],
        )

    devolucao = winthor_service.buscar_devolucao(numero_pedido)

    # Classificar motivo de devolução por palavras-chave
    if devolucao and devolucao.observacao:
        devolucao.categoria = await ai_service.classificar_motivo_devolucao(
            devolucao.observacao
        )

    # Fusion: só consulta se temos NUMCAR e CODCLI
    fusion = None
    if winthor.numero_carga and winthor.codigo_cliente:
        fusion = fusion_service.buscar_status_entrega(
            numcar=winthor.numero_carga,
            codcli=winthor.codigo_cliente,
        )
        # Enriquecer com posição na fila
        if fusion and fusion.integrado:
            fila = fusion_service.buscar_posicao_fila(
                numcar=winthor.numero_carga,
                codcli=winthor.codigo_cliente,
            )
            if fila:
                fusion.total_na_rota = fila.get("total_na_rota")
                fusion.ja_finalizados = fila.get("ja_finalizados")
                fusion.faltam_na_frente = fila.get("faltam_na_frente")

    status = montar_status_pedido(winthor, devolucao, fusion)

    # Formatar resposta via template
    status.resposta_formatada = ai_service.formatar_resposta(status)

    return status


def _nao_encontrado() -> StatusPedido:
    return StatusPedido(
        status=StatusUnificado.NAO_ENCONTRADO,
        descricao=STATUS_DESCRICAO[StatusUnificado.NAO_ENCONTRADO],
    )


async def _resolver_por_nota(numero_nota: int) -> StatusPedido:
    winthor = winthor_service.buscar_por_nota(numero_nota)
    if not winthor or not winthor.numero_pedido:
        return _nao_encontrado()
    return await _resolver_pedido(winthor.numero_pedido)


async def _resolver_por_cliente(codigo_cliente: int) -> StatusPedido:
    pedidos = winthor_service.buscar_por_cliente(codigo_cliente)
    if not pedidos or not pedidos[0].numero_pedido:
        return _nao_encontrado()
    return await _resolver_pedido(pedidos[0].numero_pedido)


async def _resolver_ambiguo(valor: int) -> StatusPedido:
    """
    Número solto (vendedor não disse se é pedido, NF ou cliente).
    Tenta em cascata: pedido → NF → cliente. Retorna o primeiro que existir.
    """
    status = await _resolver_pedido(valor)
    if status.status != StatusUnificado.NAO_ENCONTRADO:
        return status

    status = await _resolver_por_nota(valor)
    if status.status != StatusUnificado.NAO_ENCONTRADO:
        return status

    return await _resolver_por_cliente(valor)


@router.get("", response_model=StatusPedido, summary="Consulta livre (detecta o tipo)")
async def consulta_livre(q: str = Query(..., description="Número do pedido, NF ou código do cliente")):
    """
    Recebe qualquer texto. Se o vendedor disser o tipo ("nf 123", "cliente 45"),
    respeita. Se vier só um número (ambíguo), tenta pedido → NF → cliente.
    """
    parsed = ai_service.parse_consulta(q)
    tipo = parsed.get("tipo")
    valor = parsed.get("valor")

    if not tipo or not valor:
        raise HTTPException(
            status_code=422,
            detail="Não foi possível identificar o tipo de consulta. "
                   "Informe um número de pedido, NF ou código de cliente.",
        )

    try:
        valor_int = int(valor)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Valor '{valor}' não é numérico.")

    # Número solto → cascata pedido → NF → cliente (não dá pra saber o tipo com certeza)
    if parsed.get("confianca") != "alta":
        return await _resolver_ambiguo(valor_int)

    # Tipo citado explicitamente pelo vendedor → respeita
    if tipo == "pedido":
        return await _resolver_pedido(valor_int)
    if tipo == "nota":
        return await _resolver_por_nota(valor_int)
    if tipo == "cliente":
        return await _resolver_por_cliente(valor_int)

    raise HTTPException(status_code=422, detail=f"Tipo de consulta desconhecido: {tipo}")


@router.get("/pedido/{numero}", response_model=StatusPedido, summary="Buscar por número do pedido")
async def consulta_por_pedido(numero: int):
    return await _resolver_pedido(numero)


@router.get("/nota/{numero}", response_model=StatusPedido, summary="Buscar por número da NF")
async def consulta_por_nota(numero: int):
    winthor = winthor_service.buscar_por_nota(numero)
    if not winthor or not winthor.numero_pedido:
        return StatusPedido(
            status=StatusUnificado.NAO_ENCONTRADO,
            descricao=STATUS_DESCRICAO[StatusUnificado.NAO_ENCONTRADO],
        )
    return await _resolver_pedido(winthor.numero_pedido)


@router.get("/cliente/{codigo}", response_model=list[StatusPedido], summary="Últimos pedidos de um cliente")
async def consulta_por_cliente(codigo: int):
    pedidos = winthor_service.buscar_por_cliente(codigo)
    if not pedidos:
        return []
    resultados = []
    for p in pedidos[:5]:
        if p.numero_pedido:
            resultados.append(await _resolver_pedido(p.numero_pedido))
    return resultados
