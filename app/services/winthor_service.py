"""
Serviço Winthor — consultas de status de pedido.
Somente leitura. Três formas de busca: por pedido, por NF ou por cliente.

Tabelas e campos confirmados em produção (Projeto Principal):
  PCPEDC      NUMPED, CODCLI, CODUSUR, DATA, DTLIBERA, POSICAO, VLATEND, TOTPESO, DTCANCEL
  PCCLIENT    CODCLI, CLIENTE, FANTASIA, MUNICENT, ESTENT, CODPRACA
  PCUSUARI    CODUSUR, NOME, CODSUPERVISOR
  PCNFSAID    NUMPED, NUMNOTA, NUMTRANSVENDA, DTSAIDA, NUMCAR, CODMOTORISTA,
              DTCANCEL, VLTOTAL, TOTPESOBRUTO, CODCLI, CODUSUR, MOTORISTAVEICULO
  PCCARREG    NUMCAR, CODMOTORISTA, DTSAIDA
  PCEMPR      MATRICULA, NOME, SITUACAO
  PCNFENT     NUMTRANSENT, NUMNOTA, DTENTRADA, CODFISCAL, TIPODESCARGA, OBS, CODDEVOL, TOTPESO
  PCESTCOM    NUMTRANSENT, NUMTRANSVENDA, VLDEVOLUCAO
  PCTABDEV    CODDEVOL, MOTIVO
  PCSUPERV    CODSUPERVISOR, NOME

Campo CORRIGIDO: PCNFSAID.NUMTRANSVENDA (era incorretamente NUMTRANSACAO).
Motorista: PCCARREG.CODMOTORISTA → PCEMPR.MATRICULA / PCEMPR.NOME.
"""
import logging
from typing import Optional

from app.database.oracle import execute_query
from app.schemas.status import DadosWinthor, DadosDevolucao

logger = logging.getLogger(__name__)

_CLIENTES_EXCLUIDOS = "(2, 3, 7448, 19911)"
_CFOPS_DEVOLUCAO    = "('131','132','231','232','199','299')"
_TIPOS_DESCARGA     = "('6','7','T')"


# ── SQL principal: status do pedido por NUMPED ────────────────────────────────

_SQL_POR_PEDIDO = f"""
SELECT
    ped.NUMPED                                            AS numero_pedido,
    ped.CODCLI                                            AS codigo_cliente,
    cli.CLIENTE                                           AS nome_cliente,
    cli.MUNICENT                                          AS cidade,
    cli.ESTENT                                            AS uf,
    ped.CODUSUR                                           AS codigo_rca,
    usu.NOME                                              AS nome_rca,
    ped.DATA                                              AS data_pedido,
    NVL(ped.DTLIBERA, ped.DATA)                           AS data_liberacao,
    ped.POSICAO                                           AS status_pedido,
    NVL(ped.VLATEND, 0)                                   AS valor_pedido,
    nf.NUMNOTA                                            AS numero_nota,
    nf.DTSAIDA                                            AS data_faturamento,
    nf.NUMCAR                                             AS numero_carga,
    car.DTSAIDA                                           AS data_saida_carga,
    car.CODMOTORISTA                                      AS codigo_motorista,
    NVL(
        emp.NOME,
        CASE WHEN nf.MOTORISTAVEICULO IS NOT NULL
                  AND LENGTH(TRIM(nf.MOTORISTAVEICULO)) > 0
             THEN nf.MOTORISTAVEICULO END
    )                                                     AS nome_motorista
FROM PCPEDC ped
LEFT JOIN PCCLIENT  cli ON cli.CODCLI    = ped.CODCLI
LEFT JOIN PCUSUARI  usu ON usu.CODUSUR   = ped.CODUSUR
LEFT JOIN PCNFSAID  nf  ON nf.NUMPED     = ped.NUMPED
                       AND nf.DTCANCEL  IS NULL
LEFT JOIN PCCARREG  car ON car.NUMCAR    = nf.NUMCAR
LEFT JOIN PCEMPR    emp ON emp.MATRICULA = car.CODMOTORISTA
WHERE ped.NUMPED = :numero_pedido
  AND ped.CODCLI NOT IN {_CLIENTES_EXCLUIDOS}
ORDER BY nf.DTSAIDA DESC NULLS LAST
FETCH FIRST 1 ROWS ONLY
"""

# ── SQL principal: status por NUMNOTA ────────────────────────────────────────

_SQL_POR_NOTA = f"""
SELECT
    ped.NUMPED                                            AS numero_pedido,
    ped.CODCLI                                            AS codigo_cliente,
    cli.CLIENTE                                           AS nome_cliente,
    cli.MUNICENT                                          AS cidade,
    cli.ESTENT                                            AS uf,
    ped.CODUSUR                                           AS codigo_rca,
    usu.NOME                                              AS nome_rca,
    ped.DATA                                              AS data_pedido,
    NVL(ped.DTLIBERA, ped.DATA)                           AS data_liberacao,
    ped.POSICAO                                           AS status_pedido,
    NVL(ped.VLATEND, 0)                                   AS valor_pedido,
    nf.NUMNOTA                                            AS numero_nota,
    nf.DTSAIDA                                            AS data_faturamento,
    nf.NUMCAR                                             AS numero_carga,
    car.DTSAIDA                                           AS data_saida_carga,
    car.CODMOTORISTA                                      AS codigo_motorista,
    NVL(
        emp.NOME,
        CASE WHEN nf.MOTORISTAVEICULO IS NOT NULL
                  AND LENGTH(TRIM(nf.MOTORISTAVEICULO)) > 0
             THEN nf.MOTORISTAVEICULO END
    )                                                     AS nome_motorista
FROM PCNFSAID nf
JOIN  PCPEDC   ped ON ped.NUMPED   = nf.NUMPED
LEFT JOIN PCCLIENT  cli ON cli.CODCLI    = ped.CODCLI
LEFT JOIN PCUSUARI  usu ON usu.CODUSUR   = ped.CODUSUR
LEFT JOIN PCCARREG  car ON car.NUMCAR    = nf.NUMCAR
LEFT JOIN PCEMPR    emp ON emp.MATRICULA = car.CODMOTORISTA
WHERE nf.NUMNOTA  = :numero_nota
  AND nf.DTCANCEL IS NULL
  AND ped.CODCLI NOT IN {_CLIENTES_EXCLUIDOS}
FETCH FIRST 1 ROWS ONLY
"""

# ── SQL principal: últimos pedidos por CODCLI ────────────────────────────────

_SQL_POR_CLIENTE = f"""
SELECT
    ped.NUMPED                                            AS numero_pedido,
    ped.CODCLI                                            AS codigo_cliente,
    cli.CLIENTE                                           AS nome_cliente,
    cli.MUNICENT                                          AS cidade,
    cli.ESTENT                                            AS uf,
    ped.CODUSUR                                           AS codigo_rca,
    usu.NOME                                              AS nome_rca,
    ped.DATA                                              AS data_pedido,
    NVL(ped.DTLIBERA, ped.DATA)                           AS data_liberacao,
    ped.POSICAO                                           AS status_pedido,
    NVL(ped.VLATEND, 0)                                   AS valor_pedido,
    nf.NUMNOTA                                            AS numero_nota,
    nf.DTSAIDA                                            AS data_faturamento,
    nf.NUMCAR                                             AS numero_carga,
    car.DTSAIDA                                           AS data_saida_carga,
    car.CODMOTORISTA                                      AS codigo_motorista,
    NVL(
        emp.NOME,
        CASE WHEN nf.MOTORISTAVEICULO IS NOT NULL
                  AND LENGTH(TRIM(nf.MOTORISTAVEICULO)) > 0
             THEN nf.MOTORISTAVEICULO END
    )                                                     AS nome_motorista
FROM PCPEDC ped
LEFT JOIN PCCLIENT  cli ON cli.CODCLI    = ped.CODCLI
LEFT JOIN PCUSUARI  usu ON usu.CODUSUR   = ped.CODUSUR
LEFT JOIN PCNFSAID  nf  ON nf.NUMPED     = ped.NUMPED
                       AND nf.DTCANCEL  IS NULL
LEFT JOIN PCCARREG  car ON car.NUMCAR    = nf.NUMCAR
LEFT JOIN PCEMPR    emp ON emp.MATRICULA = car.CODMOTORISTA
WHERE ped.CODCLI = :codigo_cliente
  AND ped.CODCLI NOT IN {_CLIENTES_EXCLUIDOS}
  AND NVL(ped.DTLIBERA, ped.DATA) >= SYSDATE - 30
ORDER BY NVL(ped.DTLIBERA, ped.DATA) DESC
FETCH FIRST 5 ROWS ONLY
"""

# ── SQL devolução — NUMTRANSVENDA (campo correto em PCNFSAID) ─────────────────
# Caminho confirmado no Projeto Principal (devolucaoMotoristaController.js):
#   PCNFENT → PCESTCOM via NUMTRANSENT → PCNFSAID via NUMTRANSVENDA
#   Motivo oficial: PCNFENT.CODDEVOL → PCTABDEV.MOTIVO

_SQL_DEVOLUCAO = f"""
SELECT
    dev.NUMNOTA                                           AS nota_devolucao,
    dev.DTENTRADA                                         AS data_devolucao,
    dev.CODFISCAL                                         AS cfop,
    NVL(td.MOTIVO, dev.OBS)                               AS observacao,
    NVL(ec.VLDEVOLUCAO, 0)                                AS valor_devolvido
FROM  PCNFSAID  nf
JOIN  PCESTCOM  ec  ON ec.NUMTRANSVENDA = nf.NUMTRANSVENDA
JOIN  PCNFENT   dev ON dev.NUMTRANSENT  = ec.NUMTRANSENT
LEFT JOIN PCTABDEV td ON td.CODDEVOL    = dev.CODDEVOL
WHERE nf.NUMPED = :numero_pedido
  AND nf.DTCANCEL IS NULL
  AND dev.CODFISCAL    IN {_CFOPS_DEVOLUCAO}
  AND dev.TIPODESCARGA IN {_TIPOS_DESCARGA}
  AND NVL(dev.OBS, 'X') <> 'NF CANCELADA'
ORDER BY dev.DTENTRADA DESC
FETCH FIRST 1 ROWS ONLY
"""

# ── SQL alertas: liberados sem fatura ─────────────────────────────────────────

SQL_ALERTAS_SEM_FATURA = f"""
SELECT
    ped.NUMPED                                            AS numero_pedido,
    ped.CODCLI                                            AS codigo_cliente,
    cli.CLIENTE                                           AS nome_cliente,
    ped.CODUSUR                                           AS codigo_rca,
    usu.NOME                                              AS nome_rca,
    NVL(ped.DTLIBERA, ped.DATA)                           AS data_liberacao,
    ROUND((SYSDATE - NVL(ped.DTLIBERA, ped.DATA)) * 24, 1) AS horas_parado
FROM PCPEDC ped
LEFT JOIN PCCLIENT  cli ON cli.CODCLI  = ped.CODCLI
LEFT JOIN PCUSUARI  usu ON usu.CODUSUR = ped.CODUSUR
WHERE ped.POSICAO IN ('L', 'M')
  AND ROUND((SYSDATE - NVL(ped.DTLIBERA, ped.DATA)) * 24, 1) >= :horas_limite
  AND NVL(ped.DTLIBERA, ped.DATA) >= SYSDATE - 30
  AND ped.CODCLI NOT IN {_CLIENTES_EXCLUIDOS}
  AND NOT EXISTS (
      SELECT 1 FROM PCNFSAID fat
      WHERE fat.NUMPED   = ped.NUMPED
        AND fat.DTCANCEL IS NULL
  )
ORDER BY horas_parado DESC
"""

# ── SQL alertas: faturados sem carga ─────────────────────────────────────────

SQL_ALERTAS_FATURADO_SEM_CARGA = f"""
SELECT
    ped.NUMPED                                            AS numero_pedido,
    nf.NUMNOTA                                            AS numero_nota,
    cli.CLIENTE                                           AS nome_cliente,
    usu.NOME                                              AS nome_rca,
    nf.DTSAIDA                                            AS data_faturamento,
    ROUND((SYSDATE - nf.DTSAIDA) * 24, 1)                AS horas_sem_carga
FROM  PCNFSAID  nf
JOIN  PCPEDC    ped ON ped.NUMPED  = nf.NUMPED
LEFT JOIN PCCLIENT  cli ON cli.CODCLI  = nf.CODCLI
LEFT JOIN PCUSUARI  usu ON usu.CODUSUR = nf.CODUSUR
WHERE nf.DTCANCEL IS NULL
  AND NVL(nf.NUMCAR, 0) = 0
  AND nf.DTSAIDA >= SYSDATE - 7
  AND ROUND((SYSDATE - nf.DTSAIDA) * 24, 1) >= :horas_limite
  AND nf.CODCLI NOT IN {_CLIENTES_EXCLUIDOS}
ORDER BY horas_sem_carga DESC
"""


# ── Funções públicas ──────────────────────────────────────────────────────────

def buscar_por_pedido(numero_pedido: int) -> Optional[DadosWinthor]:
    rows = execute_query(_SQL_POR_PEDIDO, {"numero_pedido": numero_pedido})
    if not rows:
        return None
    return DadosWinthor(**rows[0])


def buscar_por_nota(numero_nota: int) -> Optional[DadosWinthor]:
    rows = execute_query(_SQL_POR_NOTA, {"numero_nota": numero_nota})
    if not rows:
        return None
    return DadosWinthor(**rows[0])


def buscar_por_cliente(codigo_cliente: int) -> list[DadosWinthor]:
    rows = execute_query(_SQL_POR_CLIENTE, {"codigo_cliente": codigo_cliente})
    return [DadosWinthor(**r) for r in rows]


def buscar_devolucao(numero_pedido: int) -> Optional[DadosDevolucao]:
    try:
        rows = execute_query(_SQL_DEVOLUCAO, {"numero_pedido": numero_pedido})
        if not rows:
            return None
        return DadosDevolucao(**rows[0])
    except Exception as exc:
        # Query de devolução pendente de mapeamento de colunas corretas no PCNFENT
        logger.warning("Devolução ignorada para pedido %s: %s", numero_pedido, exc)
        return None


def buscar_alertas_sem_fatura(horas_limite: int) -> list[dict]:
    return execute_query(SQL_ALERTAS_SEM_FATURA, {"horas_limite": horas_limite})


def buscar_alertas_faturado_sem_carga(horas_limite: int) -> list[dict]:
    return execute_query(SQL_ALERTAS_FATURADO_SEM_CARGA, {"horas_limite": horas_limite})
