"""
Testes das funções puras dos alertas proativos ao vendedor:
  - normalização de telefone para o formato da Evolution API
  - montagem da mensagem (entregue / devolvido)
  - deduplicação via SQLite local
"""
from datetime import datetime

import pytest

from app.database import local
from app.schemas.status import (
    DadosWinthor, DadosDevolucao, DadosFusion,
    StatusPedido, StatusUnificado, STATUS_DESCRICAO,
)
from app.services import notificacao_service as ns


# ── normalizar_telefone ───────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada, esperado", [
    ("(81) 99999-9999", "5581999999999"),   # celular com máscara → +55
    ("81999999999",     "5581999999999"),   # 11 dígitos (DDD+9) → +55
    ("8133334444",      "558133334444"),     # 10 dígitos (fixo) → +55
    ("5581999999999",   "5581999999999"),    # já com 55 → inalterado
    ("081999999999",    "5581999999999"),    # zero à esquerda removido
])
def test_normalizar_telefone_validos(entrada, esperado):
    assert ns.normalizar_telefone(entrada) == esperado


@pytest.mark.parametrize("entrada", [None, "", "   ", "123", "abc"])
def test_normalizar_telefone_invalidos(entrada):
    assert ns.normalizar_telefone(entrada) is None


def test_normalizar_telefone_sem_ddd_sem_padrao_retorna_none():
    # 9 dígitos (celular sem DDD) e sem DDD padrão → não dá pra resolver
    assert ns.normalizar_telefone("986016410") is None
    assert ns.normalizar_telefone("99922-4980") is None


@pytest.mark.parametrize("entrada, esperado", [
    ("986016410",      "5581986016410"),    # 9 dígitos sem DDD → usa DDD padrão
    ("99922-4980",     "5581999224980"),    # idem com máscara
    ("9.9555-5843",    "5581995555843"),    # idem com ponto
    ("9 8535-2663",    "5581985352663"),    # idem com espaço
])
def test_normalizar_telefone_aplica_ddd_padrao(entrada, esperado):
    assert ns.normalizar_telefone(entrada, ddd_padrao="81") == esperado


def test_normalizar_telefone_nao_sobrescreve_ddd_existente():
    # já tem DDD próprio (85) → o DDD padrão NÃO deve ser aplicado
    assert ns.normalizar_telefone("85 99736-8185", ddd_padrao="81") == "5585997368185"


# ── vendedor_ativo (vendedores desligados têm nome prefixado com "OF ") ────────

@pytest.mark.parametrize("nome", [
    "OF João Marcos",      # desligado
    "of joão",             # case-insensitive
    "  OF Maria",          # espaço à esquerda
    "OF  Pedro",           # espaço duplo
])
def test_vendedor_inativo(nome):
    assert ns.vendedor_ativo(nome) is False


@pytest.mark.parametrize("nome", [
    "João Marcos",         # ativo
    "OFICINA CENTRAL",     # "OF" sem espaço não conta
    "OFELIA SOUZA",        # idem
])
def test_vendedor_ativo(nome):
    assert ns.vendedor_ativo(nome) is True


# ── montar_mensagem ───────────────────────────────────────────────────────────

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
    assert "Carlos" in msg
    assert "12345" in msg
    assert "entregue" in msg.lower()


def test_montar_mensagem_devolvido_tem_atencao():
    msg = ns.montar_mensagem(_status(StatusUnificado.DEVOLVIDO))
    assert "Atenção" in msg
    assert "devolvido" in msg.lower()
    assert "12345" in msg


def test_montar_mensagem_devolvido_inclui_motivo():
    dev = DadosDevolucao(observacao="AVARIA NO TRANSPORTE")
    msg = ns.montar_mensagem(_status(StatusUnificado.DEVOLVIDO, devolucao=dev))
    assert "AVARIA NO TRANSPORTE" in msg


# ── deduplicação SQLite ───────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    caminho = str(tmp_path / "notif.db")
    local.init_db(caminho)
    return caminho


def test_dedup_sucesso_marca_como_notificado(db):
    assert local.ja_notificado(99, "ENTREGUE", path=db) is False
    local.registrar_notificacao(
        numero_pedido=99, evento="ENTREGUE", codigo_rca=1, nome_rca="X",
        telefone="5581999999999", nome_cliente="C", mensagem="m",
        status_envio="sucesso", detalhe=None, path=db,
    )
    assert local.ja_notificado(99, "ENTREGUE", path=db) is True


def test_dedup_falha_nao_marca_como_notificado(db):
    local.registrar_notificacao(
        numero_pedido=77, evento="DEVOLVIDO", codigo_rca=1, nome_rca="X",
        telefone=None, nome_cliente="C", mensagem="m",
        status_envio="falha", detalhe="telefone inválido", path=db,
    )
    # falha deve permitir re-tentativa no próximo ciclo
    assert local.ja_notificado(77, "DEVOLVIDO", path=db) is False


def test_dedup_distingue_evento(db):
    local.registrar_notificacao(
        numero_pedido=55, evento="ENTREGUE", codigo_rca=1, nome_rca="X",
        telefone="5581999999999", nome_cliente="C", mensagem="m",
        status_envio="sucesso", detalhe=None, path=db,
    )
    assert local.ja_notificado(55, "ENTREGUE", path=db) is True
    assert local.ja_notificado(55, "DEVOLVIDO", path=db) is False
