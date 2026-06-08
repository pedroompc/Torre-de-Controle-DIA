from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class TipoAlerta(str, Enum):
    LIBERADO_SEM_FATURA       = "LIBERADO_SEM_FATURA"
    FATURADO_SEM_CARGA        = "FATURADO_SEM_CARGA"
    EM_ROTA_SEM_ATUALIZACAO   = "EM_ROTA_SEM_ATUALIZACAO"
    DEVOLUCAO_SEM_MOTIVO      = "DEVOLUCAO_SEM_MOTIVO"
    ENTREGUE_SEM_BAIXA        = "ENTREGUE_SEM_BAIXA"
    CLIENTE_RECUSOU           = "CLIENTE_RECUSOU"
    DIVERGENCIA_SISTEMAS      = "DIVERGENCIA_SISTEMAS"
    CAMINHAO_PARADO           = "CAMINHAO_PARADO"


class SeveridadeAlerta(str, Enum):
    ALTA   = "ALTA"
    MEDIA  = "MEDIA"
    BAIXA  = "BAIXA"


ALERTA_CONFIG = {
    TipoAlerta.LIBERADO_SEM_FATURA:     {"severidade": SeveridadeAlerta.ALTA,  "acao": "Verificar bloqueio de faturamento"},
    TipoAlerta.FATURADO_SEM_CARGA:      {"severidade": SeveridadeAlerta.ALTA,  "acao": "Verificar alocação no roteirizador"},
    TipoAlerta.EM_ROTA_SEM_ATUALIZACAO: {"severidade": SeveridadeAlerta.MEDIA, "acao": "Contatar motorista"},
    TipoAlerta.DEVOLUCAO_SEM_MOTIVO:    {"severidade": SeveridadeAlerta.MEDIA, "acao": "Solicitar registro do motivo"},
    TipoAlerta.ENTREGUE_SEM_BAIXA:      {"severidade": SeveridadeAlerta.MEDIA, "acao": "Verificar baixa no Winthor"},
    TipoAlerta.CLIENTE_RECUSOU:         {"severidade": SeveridadeAlerta.ALTA,  "acao": "Notificar vendedor e registrar motivo"},
    TipoAlerta.DIVERGENCIA_SISTEMAS:    {"severidade": SeveridadeAlerta.ALTA,  "acao": "Análise manual obrigatória"},
    TipoAlerta.CAMINHAO_PARADO:         {"severidade": SeveridadeAlerta.MEDIA, "acao": "Verificar ocorrência com motorista"},
}


class Alerta(BaseModel):
    tipo: TipoAlerta
    severidade: SeveridadeAlerta
    acao_sugerida: str
    numero_pedido: Optional[int] = None
    numero_nota: Optional[int] = None
    nome_cliente: Optional[str] = None
    nome_motorista: Optional[str] = None
    nome_rca: Optional[str] = None
    detalhe: str
    gerado_em: datetime = datetime.now()
