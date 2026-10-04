"""Persistencia en un solo archivo SQLite.

Dos cosas viven ahí:
- los checkpoints de LangGraph (la conversación completa), que maneja SqliteSaver;
- la tabla `sesiones`, nuestra: una fila por charla con su estado y su análisis.
"""

import os
import sqlite3
import time
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

DB = Path(os.environ.get("INTAKE_DB", "data/intake.db"))


def conectar() -> sqlite3.Connection:
    DB.parent.mkdir(exist_ok=True)
    # check_same_thread=False: FastAPI atiende requests en varios hilos.
    conn = sqlite3.connect(DB, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # lectores y escritor a la vez sin bloquearse
    conn.execute("""CREATE TABLE IF NOT EXISTS sesiones (
        thread_id   TEXT PRIMARY KEY,
        creada      REAL NOT NULL,
        ultima      REAL NOT NULL,
        turnos      INTEGER NOT NULL DEFAULT 0,
        estado      TEXT NOT NULL DEFAULT 'abierta',  -- abierta | enviada | cerrada
        email       TEXT,
        categoria   TEXT,                             -- la pone mantenimiento.py
        analisis    TEXT                              -- JSON del clasificador
    )""")
    return conn


def checkpointer() -> SqliteSaver:
    # Conexión propia: SqliteSaver la protege con su lock; la nuestra no comparte ese lock.
    saver = SqliteSaver(conectar())
    saver.setup()
    return saver


_conn = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = conectar()
    return _conn


def registrar_turno(thread_id: str) -> sqlite3.Row:
    """Crea la sesión si es nueva, suma un turno y devuelve la fila actualizada."""
    ahora = time.time()
    return conn().execute(
        """INSERT INTO sesiones (thread_id, creada, ultima, turnos) VALUES (?, ?, ?, 1)
           ON CONFLICT(thread_id) DO UPDATE SET ultima = excluded.ultima, turnos = turnos + 1
           RETURNING *""",
        (thread_id, ahora, ahora),
    ).fetchone()


def estado(thread_id: str) -> str | None:
    fila = conn().execute("SELECT estado FROM sesiones WHERE thread_id = ?", (thread_id,)).fetchone()
    return fila["estado"] if fila else None


def marcar(thread_id: str, nuevo: str, email: str | None = None) -> None:
    conn().execute("UPDATE sesiones SET estado = ?, email = coalesce(?, email) WHERE thread_id = ?",
                   (nuevo, email, thread_id))
