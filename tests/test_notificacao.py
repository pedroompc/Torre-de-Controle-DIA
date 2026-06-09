"""
Testes das funções puras dos alertas proativos (destino: grupo de supervisores):
  - montagem da mensagem (entregue / devolvido), formato de grupo
  - limpeza do nome do vendedor (remove prefixo "OF " de desligados)
  - deduplicação via SQLite local
"""
import pytest

from app.database import local
from app.schemas.status import (
    DadosWinthor, DadosDevolucao, DadosFusion,
    StatusPedido, StatusUnificado, STATUS_DESCRICAO,
)
from app.services import notificacao_service as ns


# ── nome do vendedor (vendedores desligados têm prefixo "OF ") ─────────────────

@pytest.mark.parametrize("entrada, esperado", [
    ("CARLOS ANDRADE",       "Carlos Andrade"),
    ("OF João Marcos",       "João Marcos"),     # prefixo de desligado removido
    ("  OF MAGALI ALVES",    "Magali Alves"),
    ("OFICINA CENTRAL",      "Oficina Central"),  # "OF" sem espaço não é prefixo
])
def test_nome_vendedor(entrada, esperado):
    assert ns.nome_vendedor(entrada) == esperado


def test_nome_vendedor_vazio():
    assert ns.nome_vendedor(None) == "não informado"


# ── montar_mensagem (formato de grupo) ─────────────────────────────────────────

def _status(tipo, **kw):
    winthor = DadosWinthor(
        numero_pedido=kw.get("numero_pedido", 12345),
        nome_cliente=kw.get("nome_cliente", "MERCADO SAO JOSE LTDA"),
        nome_rca=kw.get("nome_rca", "CARLOS ANDRADE"),
        nome_motorista=kw.get("nome_motorista"),
    )
    return StatusPedido(
        numero_pedido=winthor.numero_pedido,
        status=tipo,
        descricao=STATUS_DESCRICAO[tipo],
        winthor=winthor,
        devolucao=kw.get("devolucao"),
        fusion=kw.get("fusion"),
    )


def test_montar_mensagem_entregue():
    msg = ns.montar_mensagem(_status(StatusUnificado.ENTREGUE))
    assert "entregue" in msg.lower()
    assert "Pedido: 12345" in msg
    assert "Vendedor: Carlos Andrade" in msg
    assert "Cliente:" in msg


def test_montar_mensagem_devolvido():
    msg = ns.montar_mensagem(_status(StatusUnificado.DEVOLVIDO))
    assert "devolvido" in msg.lower()
    assert "Pedido: 12345" in msg
    assert "Vendedor: Carlos Andrade" in msg


def test_montar_mensagem_devolvido_inclui_motivo():
    dev = DadosDevolucao(observacao="AVARIA NO TRANSPORTE")
    msg = ns.montar_mensagem(_status(StatusUnificado.DEVOLVIDO, devolucao=dev))
    assert "AVARIA NO TRANSPORTE" in msg


def test_montar_mensagem_limpa_prefixo_of():
    msg = ns.montar_mensagem(_status(StatusUnificado.ENTREGUE, nome_rca="OF João Marcos"))
    assert "Vendedor: João Marcos" in msg
    assert "OF João" not in msg


# ── deduplicação SQLite ───────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    caminho = str(tmp_path / "notif.db")
    local.init_db(caminho)
    return caminho


def _registrar(db, **kw):
    base = dict(
        numero_pedido=99, evento="ENTREGUE", codigo_rca=1, nome_rca="X",
        destino="120363@g.us", nome_cliente="C", mensagem="m",
        status_envio="sucesso", detalhe=None, path=db,
    )
    base.update(kw)
    local.registrar_notificacao(**base)


def test_dedup_sucesso_marca_como_notificado(db):
    assert local.ja_notificado(99, "ENTREGUE", path=db) is False
    _registrar(db)
    assert local.ja_notificado(99, "ENTREGUE", path=db) is True


def test_dedup_falha_nao_marca_como_notificado(db):
    _registrar(db, numero_pedido=77, evento="DEVOLVIDO",
               status_envio="falha", detalhe="erro de envio")
    assert local.ja_notificado(77, "DEVOLVIDO", path=db) is False


def test_dedup_distingue_evento(db):
    _registrar(db, numero_pedido=55, evento="ENTREGUE")
    assert local.ja_notificado(55, "ENTREGUE", path=db) is True
    assert local.ja_notificado(55, "DEVOLVIDO", path=db) is False
