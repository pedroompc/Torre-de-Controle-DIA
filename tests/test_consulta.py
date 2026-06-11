"""
Testes da resolução de consulta:
  - parser distingue tipo explícito (nf/nota/cliente) de número solto
  - número solto cai em cascata: pedido → nota → cliente
"""
import asyncio

import app.routers.consulta as consulta
from app.services import ai_service
from app.schemas.status import (
    StatusPedido, StatusUnificado, STATUS_DESCRICAO, DadosWinthor,
)


# ── parser ─────────────────────────────────────────────────────────────────────

def test_parse_nf_explicito():
    assert ai_service.parse_consulta("nf 123456")["tipo"] == "nota"
    assert ai_service.parse_consulta("nota 123456")["tipo"] == "nota"


def test_parse_numero_solto_e_ambiguo():
    p = ai_service.parse_consulta("123456")
    # número solto não tem como saber o tipo com certeza
    assert p["confianca"] == "media"


# ── cascata pedido → nota → cliente ────────────────────────────────────────────

def _encontrado(num):
    return StatusPedido(numero_pedido=num, status=StatusUnificado.ENTREGUE, descricao="x")


def _nao_encontrado():
    return StatusPedido(
        status=StatusUnificado.NAO_ENCONTRADO,
        descricao=STATUS_DESCRICAO[StatusUnificado.NAO_ENCONTRADO],
    )


def test_ambiguo_acha_como_pedido_e_nao_tenta_nota(monkeypatch):
    chamadas = []

    async def fake_resolver(n):
        chamadas.append(n)
        return _encontrado(n)

    monkeypatch.setattr(consulta, "_resolver_pedido", fake_resolver)
    r = asyncio.run(consulta._resolver_ambiguo(999888))
    assert r.numero_pedido == 999888
    assert chamadas == [999888]  # achou como pedido, não precisou tentar NF


def test_ambiguo_cai_para_nota_quando_nao_e_pedido(monkeypatch):
    chamadas = []

    async def fake_resolver(n):
        chamadas.append(n)
        return _nao_encontrado() if n == 555 else _encontrado(n)

    monkeypatch.setattr(consulta, "_resolver_pedido", fake_resolver)
    monkeypatch.setattr(
        consulta.winthor_service, "buscar_por_nota",
        lambda v: DadosWinthor(numero_pedido=7001),
    )
    r = asyncio.run(consulta._resolver_ambiguo(555))
    assert r.numero_pedido == 7001
    assert chamadas == [555, 7001]  # tentou pedido, falhou, resolveu via NF


def test_ambiguo_nao_encontrado_em_nenhum(monkeypatch):
    async def fake_resolver(n):
        return _nao_encontrado()

    monkeypatch.setattr(consulta, "_resolver_pedido", fake_resolver)
    monkeypatch.setattr(consulta.winthor_service, "buscar_por_nota", lambda v: None)
    monkeypatch.setattr(consulta.winthor_service, "buscar_por_cliente", lambda v: [])
    r = asyncio.run(consulta._resolver_ambiguo(123456))
    assert r.status == StatusUnificado.NAO_ENCONTRADO
