"""
Roteador de descoberta de banco de dados.
Uso TEMPORÁRIO — ajuda a mapear as tabelas do Fusion no Oracle.
Remover ou proteger com autenticação antes de ir para produção.
"""
from fastapi import APIRouter, Query
from app.database.oracle import execute_query

router = APIRouter(prefix="/discovery", tags=["Discovery (temporário)"])

# ── Lista todas as tabelas do schema atual ────────────────────────────────────

@router.get("/tabelas", summary="Lista todas as tabelas do banco")
def listar_tabelas(filtro: str = Query("", description="Filtro parcial no nome da tabela")):
    """
    Lista todas as tabelas acessíveis no Oracle, ordenadas por nome.
    Use o parâmetro 'filtro' para buscar por prefixo ou palavra-chave.
    Ex: /discovery/tabelas?filtro=FUS
    """
    sql = """
    SELECT TABLE_NAME, NUM_ROWS
    FROM ALL_TABLES
    WHERE OWNER = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA')
    ORDER BY TABLE_NAME
    """
    if filtro:
        sql = f"""
    SELECT TABLE_NAME, NUM_ROWS
    FROM ALL_TABLES
    WHERE OWNER = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA')
      AND UPPER(TABLE_NAME) LIKE UPPER('%{filtro.upper()}%')
    ORDER BY TABLE_NAME
    """
    rows = execute_query(sql)
    return {"total": len(rows), "tabelas": rows}


# ── Lista colunas de uma tabela específica ────────────────────────────────────

@router.get("/colunas/{tabela}", summary="Lista colunas de uma tabela")
def listar_colunas(tabela: str):
    """
    Mostra todas as colunas, tipos e tamanhos de uma tabela.
    Ex: /discovery/colunas/PCCARREG
    """
    sql = f"""
    SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, NULLABLE
    FROM ALL_TAB_COLUMNS
    WHERE OWNER = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA')
      AND TABLE_NAME = UPPER('{tabela.upper()}')
    ORDER BY COLUMN_ID
    """
    rows = execute_query(sql)
    return {"tabela": tabela.upper(), "total_colunas": len(rows), "colunas": rows}


# ── Amostra de dados de uma tabela ────────────────────────────────────────────

@router.get("/amostra/{tabela}", summary="Mostra as primeiras 5 linhas de uma tabela")
def amostra(tabela: str):
    """
    Retorna as primeiras 5 linhas de qualquer tabela.
    Útil para entender o conteúdo das tabelas do Fusion.
    Ex: /discovery/amostra/NOME_TABELA_FUSION
    """
    sql = f"""
    SELECT * FROM {tabela.upper()}
    FETCH FIRST 5 ROWS ONLY
    """
    rows = execute_query(sql)
    return {"tabela": tabela.upper(), "linhas": rows}
