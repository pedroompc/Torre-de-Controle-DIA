"""
Serviço FusionTrak — status de entrega em tempo real.

Schema: FUSIONT (banco Oracle compartilhado com Winthor)

Tabelas utilizadas (validadas em produção):
  FUSIONT.FUSIONTRAK_INT_EVENTOS           — eventos de entrega por cliente/carga
  FUSIONT.FUSIONTRAK_INT_CARGA             — dados da viagem (rota, motorista, ETA)
  FUSIONT.FUSIONTRAK_CARGAS_ROTEIRIZADAS   — confirma se carga foi roteirizada

Tipos de evento (TIPO é VARCHAR2):
  '1'   Início do Romaneio / Em rota
  '2'   Cheguei neste Cliente
  '6'   Entrega Iniciada
  '7'   Entrega Realizada  ← ENTREGUE
  '8'   Adiar a Entrega    ← ADIADO
  '9'   Cliente Devolveu   ← DEVOLVIDO
  '10'  Devolução Parcial  ← DEVOLUCAO_PARCIAL
  '21'  Envio de Canhoto
  '998' Romaneio Finalizado
  '999' Final do Romaneio

Vínculo com Winthor:
  FUSIONTRAK_INT_EVENTOS.CARGA_FORMADA_ERP  → PCCARREG.NUMCAR  (VARCHAR2, pode ter múltiplos separados por vírgula)
  FUSIONTRAK_INT_EVENTOS.CLIENTE_CODIGO_ERP → PCCLIENT.CODCLI  (VARCHAR2)
  FUSIONTRAK_INT_CARGA.CARGAS_GERADAS_ERP   → PCCARREG.NUMCAR  (VARCHAR2, múltiplos com vírgula)
"""
import logging
from typing import Optional

from app.database.oracle import execute_query
from app.schemas.status import DadosFusion

logger = logging.getLogger(__name__)

# Prioridade de status para deduplicação de eventos
_PRIORIDADE_TIPO = {
    '7': 1, '9': 2, '10': 3, '8': 4, '6': 5, '2': 6, '1': 7
}

_TIPOS_RELEVANTES = "('1','2','6','7','8','9','10')"
_TIPOS_FINALIZADOS = "('7','9','10','8')"

# ── Query 1: status do evento mais avançado para cliente/carga ────────────────

_SQL_STATUS_PEDIDO = """
WITH status_cliente AS (
    SELECT
        CARGA_FORMADA_ERP,
        CLIENTE_CODIGO_ERP,
        TIPO,
        DESCRICAO,
        DATAHORA,
        OBS_MOTORISTA,
        MOTIVO_DEVOL_ERP,
        DESC_DEVOL_ERP,
        ROMANEIO_ID,
        VEICULO_PLACA,
        ROW_NUMBER() OVER (
            PARTITION BY CARGA_FORMADA_ERP, CLIENTE_CODIGO_ERP
            ORDER BY
                CASE TIPO
                    WHEN '7'  THEN 1
                    WHEN '9'  THEN 2
                    WHEN '10' THEN 3
                    WHEN '8'  THEN 4
                    WHEN '6'  THEN 5
                    WHEN '2'  THEN 6
                    ELSE           7
                END,
                DATAHORA DESC
        ) AS rn
    FROM FUSIONT.FUSIONTRAK_INT_EVENTOS
    WHERE TIPO IN {tipos}
)
SELECT
    ev.TIPO                                   AS tipo_evento,
    ev.DESCRICAO                              AS descricao_evento,
    ev.DATAHORA                               AS data_evento,
    ev.OBS_MOTORISTA                          AS obs_motorista,
    ev.MOTIVO_DEVOL_ERP                       AS motivo_devolucao,
    ev.DESC_DEVOL_ERP                         AS desc_devolucao,
    ev.VEICULO_PLACA                          AS placa,
    ev.ROMANEIO_ID                            AS romaneio_id,
    carga.T10_DESTINO                         AS nome_rota,
    carga.NUMCLIENTES                         AS total_clientes_rota,
    carga.T10_DATA_SAIDA                      AS data_saida,
    carga.T10_DATA_PREVISTA_TERMINO           AS previsao_termino,
    carga.T10_SITUACAO                        AS situacao_viagem
FROM status_cliente ev
LEFT JOIN FUSIONT.FUSIONTRAK_INT_CARGA carga
       ON carga.CODIGO_INT = ev.ROMANEIO_ID
WHERE ev.CLIENTE_CODIGO_ERP = TO_CHAR(:codcli)
  AND ev.rn = 1
  AND INSTR(',' || REPLACE(ev.CARGA_FORMADA_ERP,' ','') || ',',
            ',' || TO_CHAR(:numcar) || ',') > 0
""".format(tipos=_TIPOS_RELEVANTES)

# ── Query 2: posição na fila ──────────────────────────────────────────────────

_SQL_POSICAO_FILA = """
WITH pedido_eventos AS (
    SELECT CLIENTE_CODIGO_ERP, TIPO, DATAHORA
    FROM FUSIONT.FUSIONTRAK_INT_EVENTOS
    WHERE INSTR(',' || REPLACE(CARGA_FORMADA_ERP,' ','') || ',',
                ',' || TO_CHAR(:numcar) || ',') > 0
)
SELECT
    (SELECT COUNT(DISTINCT CLIENTE_CODIGO_ERP)
     FROM pedido_eventos)                                          AS total_clientes,

    (SELECT COUNT(DISTINCT CLIENTE_CODIGO_ERP)
     FROM pedido_eventos
     WHERE TIPO IN {finalizados}
       AND CLIENTE_CODIGO_ERP != TO_CHAR(:codcli))                AS ja_finalizados,

    (SELECT TIPO
     FROM pedido_eventos
     WHERE CLIENTE_CODIGO_ERP = TO_CHAR(:codcli)
       AND TIPO IN {relevantes}
     ORDER BY
         CASE TIPO
             WHEN '7' THEN 1 WHEN '9' THEN 2 WHEN '10' THEN 3
             WHEN '8' THEN 4 WHEN '6' THEN 5 WHEN '2'  THEN 6 ELSE 7
         END,
         DATAHORA DESC
     FETCH FIRST 1 ROWS ONLY)                                     AS tipo_meu_status
FROM DUAL
""".format(finalizados=_TIPOS_FINALIZADOS, relevantes=_TIPOS_RELEVANTES)

# ── Mapeamento de tipo → status legível ───────────────────────────────────────

# ── Query auxiliar: dados da viagem pelo NUMCAR ───────────────────────────────

_SQL_CARGA_POR_NUMCAR = """
SELECT
    T10_DESTINO                   AS t10_destino,
    NUMCLIENTES                   AS numclientes,
    T10_DATA_SAIDA                AS t10_data_saida,
    T10_DATA_PREVISTA_TERMINO     AS t10_data_prevista_termino,
    T10_SITUACAO                  AS t10_situacao
FROM FUSIONT.FUSIONTRAK_INT_CARGA
WHERE INSTR(',' || REPLACE(CARGAS_GERADAS_ERP,' ','') || ',',
            ',' || TO_CHAR(:numcar) || ',') > 0
ORDER BY CODIGO_INT DESC
FETCH FIRST 1 ROWS ONLY
"""

# ── Utilitários ───────────────────────────────────────────────────────────────

def _limpar(valor) -> Optional[str]:
    """Remove valores 'fantasma' que o Fusion armazena como string literal."""
    if valor is None:
        return None
    s = str(valor).strip()
    if s.upper() in ("NULL", "NONE", "''", '""', ""):
        return None
    return s


_STATUS_LABEL = {
    '7':  'ENTREGUE',
    '9':  'DEVOLVIDO',
    '10': 'DEVOLUCAO_PARCIAL',
    '8':  'ADIADO',
    '6':  'ENTREGA_EM_ANDAMENTO',
    '2':  'MOTORISTA_NO_CLIENTE',
    '1':  'EM_ROTA',
}

_STATUS_DESCRICAO = {
    'ENTREGUE':               'Entregue ao cliente',
    'DEVOLVIDO':              'Pedido devolvido pelo cliente',
    'DEVOLUCAO_PARCIAL':      'Devolução parcial registrada',
    'ADIADO':                 'Entrega adiada pelo motorista',
    'ENTREGA_EM_ANDAMENTO':   'Motorista iniciando a entrega',
    'MOTORISTA_NO_CLIENTE':   'Motorista chegou no cliente',
    'EM_ROTA':                'Carga em rota de entrega',
    'AGUARDANDO':             'Aguardando na fila de entrega',
}


# ── Funções públicas ──────────────────────────────────────────────────────────

def buscar_status_entrega(numcar: int, codcli: int) -> Optional[DadosFusion]:
    """
    Retorna o status de entrega do cliente nessa carga via FusionTrak.
    Requer o NUMCAR (de PCCARREG) e o CODCLI (de PCCLIENT).
    """
    if not numcar or not codcli:
        return None

    try:
        rows = execute_query(_SQL_STATUS_PEDIDO, {
            "numcar": numcar,
            "codcli": codcli,
        })
    except Exception as exc:
        logger.error("Erro ao consultar FusionTrak (status): %s", exc)
        return None

    if not rows:
        logger.debug("Sem eventos Fusion para NUMCAR=%s CODCLI=%s", numcar, codcli)
        return None

    r = rows[0]
    tipo = r.get("tipo_evento") or ""
    status = _STATUS_LABEL.get(tipo, "AGUARDANDO")

    # Busca dados da viagem pelo NUMCAR (fallback quando ROMANEIO_ID não bate)
    nome_rota = r.get("nome_rota")
    total_clientes = r.get("total_clientes_rota")
    data_saida = r.get("data_saida")
    previsao = r.get("previsao_termino")
    situacao = r.get("situacao_viagem")

    if not nome_rota:
        try:
            carga_rows = execute_query(_SQL_CARGA_POR_NUMCAR, {"numcar": numcar})
            if carga_rows:
                c = carga_rows[0]
                nome_rota = c.get("t10_destino")
                total_clientes = c.get("numclientes")
                data_saida = c.get("t10_data_saida")
                previsao = c.get("t10_data_prevista_termino")
                situacao = c.get("t10_situacao")
        except Exception as exc:
            logger.debug("Carga Fusion não encontrada para NUMCAR=%s: %s", numcar, exc)

    return DadosFusion(
        integrado=True,
        status_entrega=status,
        descricao_status=_STATUS_DESCRICAO.get(status, status),
        tipo_evento=tipo,
        descricao_evento=r.get("descricao_evento"),
        data_evento=r.get("data_evento"),
        obs_motorista=_limpar(r.get("obs_motorista")),
        motivo_devolucao=_limpar(r.get("motivo_devolucao")),
        desc_devolucao=_limpar(r.get("desc_devolucao")),
        placa=r.get("placa"),
        nome_rota=nome_rota,
        total_clientes_rota=total_clientes,
        data_saida=data_saida,
        previsao_termino=previsao,
        situacao_viagem=situacao,
    )


def buscar_posicao_fila(numcar: int, codcli: int) -> Optional[dict]:
    """
    Retorna a posição do cliente na fila de entregas da carga.
    """
    if not numcar or not codcli:
        return None

    try:
        rows = execute_query(_SQL_POSICAO_FILA, {
            "numcar": numcar,
            "codcli": codcli,
        })
    except Exception as exc:
        logger.error("Erro ao consultar FusionTrak (fila): %s", exc)
        return None

    if not rows:
        return None

    r = rows[0]
    total = r.get("total_clientes") or 0
    finalizados = r.get("ja_finalizados") or 0
    tipo = r.get("tipo_meu_status") or ""
    status = _STATUS_LABEL.get(tipo, "AGUARDANDO")
    faltam = max(0, total - finalizados - (1 if status in ("ENTREGUE", "DEVOLVIDO", "DEVOLUCAO_PARCIAL", "ADIADO") else 0))

    return {
        "total_na_rota": total,
        "ja_finalizados": finalizados,
        "faltam_na_frente": faltam,
        "meu_status": status,
        "descricao": _STATUS_DESCRICAO.get(status, status),
    }
