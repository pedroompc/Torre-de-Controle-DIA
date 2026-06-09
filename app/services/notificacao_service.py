"""
Alertas proativos ao vendedor.

Descobre pedidos recém-finalizados (ENTREGUE/DEVOLVIDO), confirma o status pelo
mesmo motor da consulta, deduplica pelo SQLite local e avisa o vendedor no
WhatsApp. Cada tentativa (sucesso ou falha) é registrada.

Funções puras (testáveis isoladamente):
  - normalizar_telefone(raw) -> Optional[str]
  - montar_mensagem(status)  -> str

Orquestração:
  - executar_varredura()     -> dict (resumo de 1 ciclo)
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
_RE_INATIVO = re.compile(r"^\s*OF\s+", re.IGNORECASE)


# ── Funções puras ──────────────────────────────────────────────────────────────

def vendedor_ativo(nome: Optional[str]) -> bool:
    """
    False quando o vendedor está desligado. A empresa marca quem saiu com o
    prefixo "OF " no nome (ex.: "OF João Marcos"). "OFICINA" não conta — o
    espaço após "OF" é obrigatório.
    """
    if not nome:
        return True
    return _RE_INATIVO.match(nome) is None


def normalizar_telefone(raw: Optional[str], ddd_padrao: Optional[str] = None) -> Optional[str]:
    """
    Normaliza um telefone para o formato da Evolution API: 55 + DDD + número
    (somente dígitos). Retorna None se vazio ou inválido.

    Aceita:
      - 10 dígitos (DDD + fixo)        → prefixa 55
      - 11 dígitos (DDD + celular 9)   → prefixa 55
      - 12/13 dígitos iniciando em 55  → mantém
      - 8/9 dígitos (sem DDD)          → prefixa `ddd_padrao` + 55, se informado
                                         (cadastro do Winthor costuma vir sem DDD)
    """
    if not raw:
        return None

    digitos = re.sub(r"\D", "", str(raw)).lstrip("0")

    if len(digitos) in (10, 11):
        return "55" + digitos
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        return digitos

    # Sem DDD: só dá pra resolver com um DDD padrão configurado
    ddd = re.sub(r"\D", "", ddd_padrao) if ddd_padrao else ""
    if ddd and len(digitos) in (8, 9):
        return "55" + ddd + digitos

    return None


def _primeiro_nome(nome: Optional[str]) -> str:
    if not nome or not nome.strip():
        return "vendedor"
    return nome.strip().split()[0].title()


def _titulo(texto: Optional[str]) -> str:
    return texto.strip().title() if texto else ""


def _data_curta(dt) -> Optional[str]:
    try:
        return dt.strftime("%d/%m às %H:%M")
    except Exception:
        return None


def montar_mensagem(status: StatusPedido) -> str:
    """Monta a mensagem curta e clara para o vendedor."""
    w = status.winthor
    vendedor = _primeiro_nome(w.nome_rca if w else None)
    cliente = _titulo(w.nome_cliente if w else None) or "cliente"
    numero = status.numero_pedido or (w.numero_pedido if w else None)

    if status.status == StatusUnificado.ENTREGUE:
        partes = [
            f"Olá, {vendedor}. O pedido {numero} do cliente {cliente} "
            f"foi entregue com sucesso."
        ]
        data = _data_curta(status.fusion.data_evento) if status.fusion else None
        if data:
            partes.append(f"Entregue em {data}.")
        if w and w.nome_motorista:
            partes.append(f"Motorista: {_titulo(w.nome_motorista)}.")
        return " ".join(partes)

    # DEVOLVIDO
    partes = [
        f"Olá, {vendedor}. Atenção: o pedido {numero} do cliente {cliente} "
        f"foi devolvido."
    ]
    if status.devolucao and status.devolucao.tipo_devolucao == "PARCIAL":
        partes[0] = partes[0].replace("foi devolvido.", "teve devolução parcial.")

    motivo = None
    if status.fusion:
        motivo = status.fusion.desc_devolucao or status.fusion.motivo_devolucao
    if not motivo and status.devolucao:
        motivo = status.devolucao.observacao
    if motivo:
        partes.append(f"Motivo: {motivo}.")
    return " ".join(partes)


# ── Orquestração ────────────────────────────────────────────────────────────────

async def executar_varredura() -> dict:
    """
    Roda 1 ciclo de varredura: descobre candidatos, confirma status, deduplica,
    resolve telefone, envia e registra. Nunca levanta exceção para o chamador.
    """
    # Import tardio evita import circular (consulta não importa este módulo).
    from app.routers.consulta import _resolver_pedido
    from app.services.whatsapp_service import enviar_mensagem

    resumo = {"candidatos": 0, "notificados": 0, "falhas": 0,
              "pulados": 0, "inativos": 0}

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
        w = status.winthor

        # Vendedor desligado (nome prefixado com "OF ") — não notifica
        if not vendedor_ativo(w.nome_rca if w else None):
            logger.debug("Pedido %s: vendedor inativo (%s), pulado.",
                         numped, w.nome_rca if w else None)
            resumo["inativos"] += 1
            continue

        if local.ja_notificado(numped, evento):
            resumo["pulados"] += 1
            continue

        # TELEFONE1 (preferencial) com fallback no TELEFONE2; DDD padrão p/ cadastros sem DDD
        ddd = settings.alertas_ddd_padrao
        telefone = (
            normalizar_telefone(w.telefone_rca if w else None, ddd)
            or normalizar_telefone(w.telefone_rca_alt if w else None, ddd)
        )
        mensagem = montar_mensagem(status)

        if not telefone:
            logger.warning(
                "Pedido %s (%s): telefone do vendedor ausente/inválido (%r).",
                numped, evento, w.telefone_rca if w else None,
            )
            local.registrar_notificacao(
                numero_pedido=numped, evento=evento,
                codigo_rca=w.codigo_rca if w else None,
                nome_rca=w.nome_rca if w else None,
                telefone=None, nome_cliente=w.nome_cliente if w else None,
                mensagem=mensagem, status_envio="falha",
                detalhe="telefone do vendedor ausente/inválido",
            )
            resumo["falhas"] += 1
            continue

        logger.info("Notificando vendedor %s — pedido %s %s", telefone, numped, evento)
        resultado = await enviar_mensagem(telefone, mensagem)
        enviado = bool(resultado.get("enviado"))

        local.registrar_notificacao(
            numero_pedido=numped, evento=evento,
            codigo_rca=w.codigo_rca if w else None,
            nome_rca=w.nome_rca if w else None,
            telefone=telefone, nome_cliente=w.nome_cliente if w else None,
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
