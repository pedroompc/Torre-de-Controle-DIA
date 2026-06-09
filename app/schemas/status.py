from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class StatusUnificado(str, Enum):
    EM_SEPARACAO = "EM_SEPARACAO"          # Liberado/Montado no Winthor, sem NF
    FATURADO = "FATURADO"                  # NF emitida, sem saída de carga ainda
    EM_ROTA = "EM_ROTA"                    # Carga saiu, aguardando confirmação Fusion
    ENTREGUE = "ENTREGUE"                  # Confirmado entregue (Fusion)
    DEVOLVIDO = "DEVOLVIDO"                # PCNFENT registrada — devolução confirmada
    RECUSADO = "RECUSADO"                  # Cliente recusou no ato da entrega (Fusion)
    EXCECAO = "EXCECAO"                    # Divergência entre sistemas
    NAO_ENCONTRADO = "NAO_ENCONTRADO"      # Pedido não localizado


STATUS_DESCRICAO = {
    StatusUnificado.EM_SEPARACAO:  "Pedido liberado — aguardando faturamento",
    StatusUnificado.FATURADO:      "Nota emitida — aguardando saída da carga",
    StatusUnificado.EM_ROTA:       "Carga saiu — em rota de entrega",
    StatusUnificado.ENTREGUE:      "Entregue ao cliente",
    StatusUnificado.DEVOLVIDO:     "Pedido devolvido",
    StatusUnificado.RECUSADO:      "Entrega recusada pelo cliente",
    StatusUnificado.EXCECAO:       "Divergência entre sistemas — verificar manualmente",
    StatusUnificado.NAO_ENCONTRADO: "Pedido não encontrado",
}


class DadosWinthor(BaseModel):
    numero_pedido: Optional[int] = None
    codigo_cliente: Optional[int] = None
    nome_cliente: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    codigo_rca: Optional[int] = None
    nome_rca: Optional[str] = None
    data_pedido: Optional[datetime] = None
    data_liberacao: Optional[datetime] = None
    status_pedido: Optional[str] = None       # L, M, F, C, B
    valor_pedido: Optional[float] = None
    numero_nota: Optional[int] = None
    data_faturamento: Optional[datetime] = None
    numero_carga: Optional[int] = None
    data_saida_carga: Optional[datetime] = None
    codigo_motorista: Optional[int] = None
    nome_motorista: Optional[str] = None


class DadosDevolucao(BaseModel):
    nota_devolucao: Optional[int] = None
    data_devolucao: Optional[datetime] = None
    valor_devolvido: Optional[float] = None
    valor_nota: Optional[float] = None
    cfop: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None
    tipo_devolucao: Optional[str] = None     # TOTAL ou PARCIAL


class DadosFusion(BaseModel):
    """Preenchido com dados do FusionTrak (schema FUSIONT, Oracle compartilhado)."""
    integrado: bool = False
    # Status da entrega
    status_entrega: Optional[str] = None        # ENTREGUE, DEVOLVIDO, EM_ROTA, etc.
    descricao_status: Optional[str] = None      # Texto legível do status
    tipo_evento: Optional[str] = None           # Código do tipo (VARCHAR2 no Fusion)
    descricao_evento: Optional[str] = None      # Ex: "Entrega Realizada"
    data_evento: Optional[datetime] = None      # Quando ocorreu o último evento
    # Detalhes do motorista e veículo
    placa: Optional[str] = None
    obs_motorista: Optional[str] = None
    # Devolução
    motivo_devolucao: Optional[str] = None
    desc_devolucao: Optional[str] = None
    # Dados da rota/viagem
    nome_rota: Optional[str] = None
    total_clientes_rota: Optional[int] = None
    data_saida: Optional[datetime] = None
    previsao_termino: Optional[datetime] = None
    situacao_viagem: Optional[str] = None
    # Posição na fila (preenchido separadamente)
    total_na_rota: Optional[int] = None
    ja_finalizados: Optional[int] = None
    faltam_na_frente: Optional[int] = None


class StatusPedido(BaseModel):
    numero_pedido: Optional[int] = None
    status: StatusUnificado
    descricao: str
    winthor: Optional[DadosWinthor] = None
    devolucao: Optional[DadosDevolucao] = None
    fusion: Optional[DadosFusion] = None
    resposta_formatada: Optional[str] = None   # texto gerado pela IA para o vendedor
    consultado_em: datetime = datetime.now()
