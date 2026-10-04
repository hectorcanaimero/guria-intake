"""API del widget de chat: cada mensaje del navegador entra por /api/chat."""

import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

import db
from chat import archivo, build_chat
from grafo import build_graph, procesar

MAX_TURNOS = 30        # mensajes del usuario por sesión
MAX_POR_HORA = 60      # mensajes por IP por hora

app = FastAPI()
chat = build_chat()
graph = build_graph()
log = logging.getLogger("uvicorn.error")
_recientes: dict[str, deque] = defaultdict(deque)


class Entrada(BaseModel):
    thread_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    mensaje: str = Field(min_length=1, max_length=2000)


class Salida(BaseModel):
    respuesta: str
    terminado: bool


def limitar(ip: str) -> None:
    # ponytail: contador en memoria de un solo proceso; Redis si corre más de una réplica.
    ahora, q = time.time(), _recientes[ip]
    while q and q[0] < ahora - 3600:
        q.popleft()
    if len(q) >= MAX_POR_HORA:
        raise HTTPException(429, "Demasiados mensajes. Probá de nuevo en un rato. · Muitas mensagens. Tente de novo mais tarde.")
    q.append(ahora)


def correr_grafo(destino: Path) -> None:
    # El formulario ya está en disco (lo escribió enviar_intake): si el modelo falla, el lead no se pierde.
    registro = json.loads(destino.read_text()) | {"error": None}
    try:
        registro |= procesar(registro["formulario"], graph)
    except Exception as e:
        log.exception("intake: falló el grafo")
        registro["error"] = repr(e)
    destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2))


@app.post("/api/chat")
def conversar(entrada: Entrada, request: Request, tasks: BackgroundTasks) -> Salida:
    # Detrás de Caddy, la IP real llega en X-Forwarded-For.
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    limitar(ip)

    sesion = db.registrar_turno(entrada.thread_id)
    if sesion["estado"] == "enviada":
        return Salida(respuesta="Ya recibí tu proyecto: Héctor te escribe por email en 24 h. · Já recebi seu projeto: o Héctor te escreve por e-mail em 24 h.", terminado=True)
    if sesion["estado"] == "cerrada":
        return Salida(respuesta="Esta charla terminó. Si tenés un proyecto, abrí una nueva cuando quieras. · Esta conversa terminou. Se tiver um projeto, abra uma nova quando quiser.", terminado=True)
    if sesion["turnos"] > MAX_TURNOS:
        db.marcar(entrada.thread_id, "cerrada")
        return Salida(respuesta="Llegamos al límite de esta charla: escribime por email y seguimos. · Chegamos ao limite desta conversa: me escreva por e-mail e seguimos.", terminado=True)

    config = {"configurable": {"thread_id": entrada.thread_id}}
    r = chat.invoke({"messages": [{"role": "user", "content": entrada.mensaje}]}, config)
    nuevo = db.estado(entrada.thread_id)
    if nuevo == "enviada":  # enviar_intake corrió en este turno: arranca el borrador en segundo plano
        tasks.add_task(correr_grafo, archivo(entrada.thread_id))
    return Salida(respuesta=r["messages"][-1].text, terminado=nuevo != "abierta")
