"""
Persistência local (SQLite) — somente para os alertas proativos ao vendedor.

O Oracle (Winthor/Fusion) é estritamente somente-leitura, então o histórico de
notificações enviadas e a deduplicação ficam aqui, num banco local separado.

Tabela `notificacoes_enviadas`:
  - dedup: não reenviar para o mesmo (numero_pedido, evento) já enviado com sucesso
  - log: registra cada tentativa (sucesso ou falha) com detalhe
"""
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notificacoes_enviadas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_pedido INTEGER NOT NULL,
    evento        TEXT    NOT NULL,
    codigo_rca    INTEGER,
    nome_rca      TEXT,
    destino       TEXT,
    nome_cliente  TEXT,
    mensagem      TEXT,
    status_envio  TEXT    NOT NULL,
    detalhe       TEXT,
    criado_em     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_notif_pedido_evento
    ON notificacoes_enviadas (numero_pedido, evento);
"""


def _path(path: Optional[str] = None) -> str:
    return path or settings.alertas_sqlite_path


def _conectar(path: Optional[str] = None) -> sqlite3.Connection:
    caminho = _path(path)
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Optional[str] = None) -> None:
    """Cria a tabela/índice se ainda não existirem. Idempotente."""
    with _conectar(path) as conn:
        conn.executescript(_SCHEMA)
    logger.info("SQLite de notificações pronto em %s", _path(path))


def ja_notificado(numero_pedido: int, evento: str, path: Optional[str] = None) -> bool:
    """True se já existe um envio com SUCESSO para (numero_pedido, evento)."""
    with _conectar(path) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM notificacoes_enviadas
            WHERE numero_pedido = ? AND evento = ? AND status_envio = 'sucesso'
            LIMIT 1
            """,
            (numero_pedido, evento),
        ).fetchone()
    return row is not None


def registrar_notificacao(
    *,
    numero_pedido: int,
    evento: str,
    codigo_rca: Optional[int],
    nome_rca: Optional[str],
    destino: Optional[str],
    nome_cliente: Optional[str],
    mensagem: Optional[str],
    status_envio: str,
    detalhe: Optional[str],
    path: Optional[str] = None,
) -> None:
    """Registra uma tentativa de notificação (sucesso ou falha)."""
    with _conectar(path) as conn:
        conn.execute(
            """
            INSERT INTO notificacoes_enviadas
                (numero_pedido, evento, codigo_rca, nome_rca, destino,
                 nome_cliente, mensagem, status_envio, detalhe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (numero_pedido, evento, codigo_rca, nome_rca, destino,
             nome_cliente, mensagem, status_envio, detalhe),
        )
        conn.commit()


def listar_notificacoes(limit: int = 50, path: Optional[str] = None) -> list[dict]:
    """Histórico mais recente primeiro."""
    with _conectar(path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM notificacoes_enviadas
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
