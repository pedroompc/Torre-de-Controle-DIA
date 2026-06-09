"""
Alertas proativos — avisa um GRUPO de WhatsApp (supervisores/gerentes) quando um
pedido é ENTREGUE ou DEVOLVIDO. Os supervisores repassam aos seus vendedores.

Descobre pedidos recém-finalizados, confirma o status pelo mesmo motor da
consulta, deduplica pelo SQLite local e dispara a mensagem para o grupo
configurado (`ALERTAS_GRUPO_JID`). Cada tentativa é registrada.

Funções puras (testáveis isoladamente):
  - nome_vendedor(nome) -> str   (remove o prefixo "OF " de vendedores desligados)
  - montar_mensagem(status) -> str

Orquestração:
  - executar_varredura() -> dict (resumo de 1 ciclo)
"""
import logging
import re
from typing import Optional

from app.config import settings
from app.database import local
from app.schemas.status import StatusPedido, StatusUnificado
from app.services import winthor_service

logger = logging.getLogger(__name__)

# Status unificado → rótulo do evento de notificação
_EVENTO_POR_STATUS = {
    StatusUnificado.ENTREGUE: "ENTREGUE",
    StatusUnificado.DEVOLVIDO: "DEVOLVIDO",
}

# Vendedores desligados são marcados com o prefixo "OF " no nome (convenção interna)
_RE_PREFIXO_OF = re.compile(r"^\s*OF\s+", re.IGNORECASE)


# ── Funções puras ──────────────────────────────────────────────────────────────

def nome_vendedor(nome: Optional[str]) -> str:
    """
    Nome do vendedor para exibição. Remove o prefixo "OF " usado para marcar
    desligados (ex.: "OF João Marcos" → "João Marcos"). "OFICINA" não conta —
    o espaço após "OF" é obrigatório.
    """
    if not nome or not nome.strip():
        return "não informado"
    limpo = _RE_PREFIXO_OF.sub("", nome.strip())
    return limpo.title()


def _titulo(texto: Optional[str]) -> Optional[str]:
    return texto.strip().title() if texto and texto.strip() else None


def _data_curta(dt) -> Optional[str]:
    try:
        return dt.strftime("%d/%m às %H:%M")
    except Exception:
        return None


def montar_mensagem(status: StatusPedido) -> str:
    """Monta a mensagem no formato de grupo (painel de monitoramento)."""
    w = status.winthor
    numero = status.numero_pedido or (w.numero_pedido if w else None)
    cliente = _titulo(w.nome_cliente if w else None) or "não informado"
    vendedor = nome_vendedor(w.nome_rca if w else None)

    if status.status == StatusUnificado.ENTREGUE:
        linhas = [
            "✅ Pedido entregue",
            f"Pedido: {numero}",
            f"Cliente: {cliente}",
            f"Vendedor: {vendedor}",
        ]
        data = _data_curta(status.fusion.data_evento) if status.fusion else None
        if data:
            linhas.append(f"Entregue em {data}")
        if w and w.nome_motorista:
            linhas.append(f"Motorista: {_titulo(w.nome_motorista)}")
        return "\n".join(linhas)

    # DEVOLVIDO
    parcial = bool(status.devolucao and status.devolucao.tipo_devolucao == "PARCIAL")
    linhas = [
        "⚠️ Devolução parcial" if parcial else "⚠️ Pedido devolvido",
        f"Pedido: {numero}",
        f"Cliente: {cliente}",
        f"Vendedor: {vendedor}",
    ]
    motivo = None
    if status.fusion:
        motivo = status.fusion.desc_devolucao or status.fusion.motivo_devolucao
    if not motivo and status.devolucao:
        motivo = status.devolucao.observacao
    if motivo:
        linhas.append(f"Motivo: {motivo}")
    return "\n".join(linhas)


# ── Orquestração ────────────────────────────────────────────────────────────────

async def executar_varredura() -> dict:
    """
    Roda 1 ciclo: descobre candidatos, confirma status, deduplica e dispara a
    mensagem para o grupo. Nunca levanta exceção para o chamador.
    """
    # Import tardio evita import circular (consulta não importa este módulo).
    from app.routers.consulta import _resolver_pedido
    from app.services.whatsapp_service import enviar_mensagem

    resumo = {"candidatos": 0, "notificados": 0, "falhas": 0, "pulados": 0}

    grupo = settings.alertas_grupo_jid
    if not grupo:
        logger.error("ALERTAS_GRUPO_JID não configurado — varredura abortada.")
        return resumo

    try:
        pedidos = winthor_service.buscar_pedidos_finalizados(
            settings.alertas_lookback_horas
        )
    except Exception as exc:
        logger.error("Falha ao buscar pedidos finalizados: %s", exc)
        return resumo

    for numped in pedidos:
        try:
            status = await _resolver_pedido(numped)
        except Exception as exc:
            logger.error("Erro ao resolver pedido %s na varredura: %s", numped, exc)
            continue

        evento = _EVENTO_POR_STATUS.get(status.status)
        if not evento:
            continue

        resumo["candidatos"] += 1

        if local.ja_notificado(numped, evento):
            resumo["pulados"] += 1
            continue

        w = status.winthor
        mensagem = montar_mensagem(status)

        logger.info("Notificando grupo — pedido %s %s", numped, evento)
        resultado = await enviar_mensagem(grupo, mensagem)
        enviado = bool(resultado.get("enviado"))

        local.registrar_notificacao(
            numero_pedido=numped, evento=evento,
            codigo_rca=w.codigo_rca if w else None,
            nome_rca=w.nome_rca if w else None,
            destino=grupo, nome_cliente=w.nome_cliente if w else None,
            mensagem=mensagem,
            status_envio="sucesso" if enviado else "falha",
            detalhe=resultado.get("detalhe"),
        )
        if enviado:
            resumo["notificados"] += 1
        else:
            resumo["falhas"] += 1

    logger.info("Varredura de alertas concluída: %s", resumo)
    return resumo
