"""API del widget de chat: cada mensaje del navegador entra por /api/chat."""

import json
import time
from collections import defaultdict, deque

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

import db
from chat import archivo, build_chat
from grafo import build_graph, completar_borrador

MAX_TURNOS = 30        # mensajes del usuario por sesión
MAX_POR_HORA = 60      # mensajes por IP por hora

app = FastAPI()
chat = build_chat()
graph = build_graph()
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


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def abrir_turno(entrada: Entrada, request: Request) -> Salida | None:
    """Límites y estado de la sesión. Devuelve la respuesta fija si la sesión no llega al modelo."""
    # Detrás de Caddy, la IP real llega en X-Forwarded-For.
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    limitar(ip)

    sesion = db.registrar_turno(entrada.thread_id)
    if sesion["estado"] == "enviada":
        return Salida(respuesta="Ya recibí tu proyecto: el equipo de Guria se va a poner en contacto por email. · Já recebi seu projeto: a equipe da Guria vai entrar em contato por e-mail.", terminado=True)
    if sesion["estado"] == "cerrada":
        return Salida(respuesta="Esta charla terminó. Si tenés un proyecto, abrí una nueva cuando quieras. · Esta conversa terminou. Se tiver um projeto, abra uma nova quando quiser.", terminado=True)
    if sesion["turnos"] > MAX_TURNOS:
        db.marcar(entrada.thread_id, "cerrada")
        return Salida(respuesta="Llegamos al límite de esta charla: escribime por email y seguimos. · Chegamos ao limite desta conversa: me escreva por e-mail e seguimos.", terminado=True)
    return None


def cerrar_turno(thread_id: str, tasks: BackgroundTasks) -> bool:
    nuevo = db.estado(thread_id)
    if nuevo == "enviada":  # enviar_intake corrió en este turno: arranca el borrador en segundo plano
        tasks.add_task(completar_borrador, archivo(thread_id), graph)
    return nuevo != "abierta"


def _entrada(entrada: Entrada) -> tuple[dict, dict]:
    return {"messages": [{"role": "user", "content": entrada.mensaje}]}, {"configurable": {"thread_id": entrada.thread_id}}


@app.post("/api/chat")
def conversar(entrada: Entrada, request: Request, tasks: BackgroundTasks) -> Salida:
    if fija := abrir_turno(entrada, request):
        return fija
    r = chat.invoke(*_entrada(entrada))
    return Salida(respuesta=r["messages"][-1].text, terminado=cerrar_turno(entrada.thread_id, tasks))


@app.post("/api/chat/stream")
def conversar_en_vivo(entrada: Entrada, request: Request, tasks: BackgroundTasks) -> StreamingResponse:
    """Igual que /api/chat, pero en NDJSON: {"t": "..."} por fragmento y {"fin": true, "terminado": ...} al final."""
    fija = abrir_turno(entrada, request)  # el 429 sale antes de empezar a transmitir

    def lineas():
        linea = lambda d: json.dumps(d, ensure_ascii=False) + "\n"
        if fija:
            yield linea({"t": fija.respuesta})
            yield linea({"fin": True, "terminado": True})
            return
        ultimo = None
        for chunk, meta in chat.stream(*_entrada(entrada), stream_mode="messages"):
            if meta.get("langgraph_node") != "model" or not isinstance(chunk, AIMessage) or not chunk.text:
                continue
            if ultimo and chunk.id != ultimo:  # otro mensaje del modelo (antes y después de una tool)
                yield linea({"t": "\n\n"})
            ultimo = chunk.id
            yield linea({"t": chunk.text})
        yield linea({"fin": True, "terminado": cerrar_turno(entrada.thread_id, tasks)})

    return StreamingResponse(lineas(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no"})
