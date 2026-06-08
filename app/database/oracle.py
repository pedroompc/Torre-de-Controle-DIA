"""
Conexão Oracle — somente leitura (SELECT).
Reutiliza a mesma estrutura do monitor-winthor com bloqueio anti-DML.
"""
import re
import logging
from contextlib import contextmanager
from typing import Generator

import oracledb

from app.config import settings

logger = logging.getLogger(__name__)

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|MERGE|CREATE)\b",
    re.IGNORECASE,
)


def _assert_readonly(sql: str) -> None:
    match = _FORBIDDEN.search(sql)
    if match:
        raise ValueError(
            f"SQL bloqueado: '{match.group()}' não é permitido. "
            "Esta aplicação executa somente SELECT."
        )


def _dsn() -> str:
    return f"{settings.oracle_host}:{settings.oracle_port}/{settings.oracle_service_name}"


def get_connection() -> oracledb.Connection:
    try:
        conn = oracledb.connect(
            user=settings.oracle_user,
            password=settings.oracle_password,
            dsn=_dsn(),
        )
        logger.debug("Conexão Oracle estabelecida.")
        return conn
    except oracledb.DatabaseError as exc:
        (error,) = exc.args
        logger.error("Falha Oracle ORA-%s", error.code)
        raise ConnectionError(
            f"Não foi possível conectar ao Oracle. ORA-{error.code}"
        ) from exc


@contextmanager
def oracle_connection() -> Generator[oracledb.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def execute_query(sql: str, params: dict | None = None) -> list[dict]:
    _assert_readonly(sql)
    params = params or {}

    with oracle_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.callTimeout = settings.oracle_query_timeout_seconds * 1000
            cursor.execute(sql, params)
            columns = [col[0].lower() for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            logger.debug("Query retornou %d linha(s).", len(rows))
            return rows
        except oracledb.DatabaseError as exc:
            (error,) = exc.args
            if error.code == 1013:
                raise TimeoutError(
                    f"Timeout após {settings.oracle_query_timeout_seconds}s."
                ) from exc
            logger.error("Erro Oracle ORA-%s: %s", error.code, error.message)
            raise RuntimeError(f"Erro Oracle ORA-{error.code}: {error.message}") from exc
        finally:
            cursor.close()


def check_connection() -> dict:
    try:
        with oracle_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM DUAL")
            c.close()
        return {"status": "ok", "mensagem": "Conexão Oracle bem-sucedida."}
    except Exception as exc:
        return {"status": "erro", "mensagem": str(exc)}
