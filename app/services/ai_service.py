"""
Serviço de formatação de respostas — sem IA externa.

Parser: regex simples para extrair número de pedido, NF ou cliente.
Respostas: templates fixos por status, formatados para WhatsApp.

Quando a IA for necessária (queries ambíguas, conversa multi-turno),
basta descomentar as funções Claude no final do arquivo e trocar as
chamadas em consulta.py.
"""
import re
import logging
from typing import Optional

from app.schemas.status import StatusPedido, StatusUnificado

logger = logging.getLogger(__name__)

# ── Emojis por status ─────────────────────────────────────────────────────────

_EMOJI = {
    StatusUnificado.ENTREGUE:          "✅",
    StatusUnificado.DEVOLVIDO:         "❌",
    StatusUnificado.EM_ROTA:           "🚚",
    StatusUnificado.FATURADO:          "📦",
    StatusUnificado.EM_SEPARACAO:      "🏭",
    StatusUnificado.EXCECAO:           "⚠️",
    StatusUnificado.NAO_ENCONTRADO:    "❓",
}

# ── Categorias de devolução (mantidas para uso futuro com IA) ─────────────────

CATEGORIAS_DEVOLUCAO = [
    "CLIENTE_AUSENTE",
    "RECUSA_PRECO",
    "RECUSA_PRODUTO",
    "ENDERECO_NAO_LOCALIZADO",
    "PROBLEMA_DOCUMENTO",
    "PROBLEMA_VEICULO",
    "CAPACIDADE_PAGAMENTO",
    "DIVERGENCIA_PEDIDO",
    "FORCA_MAIOR",
    "SEM_MOTIVO_INFORMADO",
]


# ── 1. Parser de consulta ─────────────────────────────────────────────────────

def parse_consulta(mensagem: str) -> dict:
    """
    Extrai tipo e valor de busca da mensagem do vendedor via regex.
    Retorna: {"tipo": "pedido"|"nota"|"cliente", "valor": str, "confianca": str}
    """
    texto = mensagem.strip()

    # Padrões explícitos (menção ao tipo)
    padroes = [
        (r"(?:pedido|ped\.?|order)[^\d]*(\d{5,12})",  "pedido"),
        (r"(?:nf|nota\s*fiscal|nfe)[^\d]*(\d{5,10})", "nota"),
        (r"(?:nf|nota)\s+(\d{5,10})",                 "nota"),
        (r"(?:cliente|cli\.?|cod\.?)[^\d]*(\d{3,8})", "cliente"),
    ]
    for padrao, tipo in padroes:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            return {"tipo": tipo, "valor": m.group(1), "confianca": "alta"}

    # Apenas número — assume pedido se >= 6 dígitos, cliente se <= 5
    numeros = re.findall(r"\b(\d{4,12})\b", texto)
    if numeros:
        numero = numeros[0]
        tipo = "pedido" if len(numero) >= 6 else "cliente"
        return {"tipo": tipo, "valor": numero, "confianca": "media"}

    return {"tipo": None, "valor": None, "confianca": "baixa"}


# ── 2. Formatador de resposta ─────────────────────────────────────────────────

def formatar_resposta(status: StatusPedido) -> str:
    """
    Formata o StatusPedido em texto para WhatsApp.
    Linhas separadas, emojis por status, máximo de informação útil.
    """
    emoji = _EMOJI.get(status.status, "ℹ️")
    w = status.winthor
    f = status.fusion

    if status.status == StatusUnificado.NAO_ENCONTRADO:
        return (
            "❓ *Pedido não encontrado*\n"
            "Verifique o número e tente novamente."
        )

    linhas = []

    # Cabeçalho
    linhas.append(f"{emoji} *{status.descricao.upper()}*")
    if w:
        linhas.append(f"Pedido: {w.numero_pedido or '-'}")
        if w.nome_cliente:
            linhas.append(f"Cliente: {w.nome_cliente}")
        if w.cidade:
            linhas.append(f"Cidade: {w.cidade}/{w.uf or ''}")
        if w.nome_rca:
            linhas.append(f"Vendedor: {w.nome_rca}")

    # Nota e data
    if w and w.numero_nota:
        data_fat = w.data_faturamento.strftime("%d/%m/%Y") if w.data_faturamento else "-"
        linhas.append(f"NF: {w.numero_nota} | Faturado: {data_fat}")

    # Motorista e placa
    motorista = (f and f.placa and f"{w.nome_motorista or '-'} | Placa: {f.placa}") \
                or (w and w.nome_motorista) or None
    if motorista:
        linhas.append(f"Motorista: {motorista}")

    # Bloco Fusion
    if f and f.integrado:

        # Data do evento principal
        if f.data_evento:
            data_ev = f.data_evento.strftime("%d/%m/%Y as %H:%M")
            if status.status == StatusUnificado.ENTREGUE:
                linhas.append(f"Entregue em: {data_ev}")
            elif status.status == StatusUnificado.DEVOLVIDO:
                linhas.append(f"Devolvido em: {data_ev}")
            elif status.status == StatusUnificado.EM_ROTA:
                linhas.append(f"Ultimo registro: {data_ev}")

        # Motivo devolução
        if f.motivo_devolucao:
            linhas.append(f"Motivo: {f.motivo_devolucao}")

        # Rota e posição na fila
        if f.nome_rota:
            linhas.append(f"Rota: {f.nome_rota}")

        if f.total_na_rota:
            if f.faltam_na_frente == 0:
                linhas.append(
                    f"Posicao na rota: atendido "
                    f"({f.ja_finalizados} de {f.total_na_rota} finalizados)"
                )
            elif f.faltam_na_frente and f.faltam_na_frente > 0:
                linhas.append(
                    f"Posicao na rota: {f.faltam_na_frente} cliente(s) na frente"
                )

        # Previsão de término da rota
        if f.previsao_termino and status.status == StatusUnificado.EM_ROTA:
            linhas.append(
                f"Previsao termino rota: "
                f"{f.previsao_termino.strftime('%d/%m/%Y as %H:%M')}"
            )

        # Observação do motorista
        if f.obs_motorista:
            linhas.append(f"Obs motorista: {f.obs_motorista}")

    # Status sem Fusion — só Winthor
    elif w:
        if w.data_saida_carga:
            linhas.append(
                f"Saiu em carga: {w.data_saida_carga.strftime('%d/%m/%Y')}"
            )

    return "\n".join(linhas)


# ── 3. Classificador de motivo de devolução (heurística simples) ──────────────

_PALAVRAS_CATEGORIA = {
    "CLIENTE_AUSENTE":       ["fechado", "ausente", "nao tinha", "porta fechada", "sem responsavel"],
    "RECUSA_PRECO":          ["preco", "valor", "caro", "desistiu", "desistencia"],
    "RECUSA_PRODUTO":        ["produto", "avaria", "avariado", "errado", "vencido", "danificado"],
    "ENDERECO_NAO_LOCALIZADO": ["endereco", "nao encontrou", "nao localiz", "mudou", "sem acesso"],
    "PROBLEMA_DOCUMENTO":    ["nf", "nota fiscal", "cnpj", "documento", "fiscal", "bloqueio"],
    "PROBLEMA_VEICULO":      ["veiculo", "caminhao", "pneu", "acidente", "quebrou", "avaria veiculo"],
    "CAPACIDADE_PAGAMENTO":  ["limite", "credito", "debito", "bloqueado", "sem limite", "cobranca"],
    "DIVERGENCIA_PEDIDO":    ["quantidade", "faltando", "diferente", "duplicado", "duplicata", "item"],
    "FORCA_MAIOR":           ["chuva", "alagamento", "bloqueio", "greve", "acidente via"],
}

async def classificar_motivo_devolucao(texto_motivo: Optional[str]) -> str:
    """Classifica motivo de devolução por palavras-chave."""
    if not texto_motivo or not texto_motivo.strip():
        return "SEM_MOTIVO_INFORMADO"

    t = texto_motivo.lower()
    for categoria, palavras in _PALAVRAS_CATEGORIA.items():
        if any(p in t for p in palavras):
            return categoria

    return "SEM_MOTIVO_INFORMADO"
