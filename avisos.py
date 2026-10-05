"""Avisos al equipo por el webhook de n8n (que los reenvía por WhatsApp).

Todos los payloads llevan `tipo` y `text`; las propuestas además llevan el PDF en
base64 en `archivo`, listo para el sendMedia de Evolution API.
"""

import base64
import json
import os
import urllib.request
from pathlib import Path


def enviar(payload: dict) -> None:
    url = os.environ.get("REPORTE_WEBHOOK_URL")
    if not url:
        raise RuntimeError("Falta REPORTE_WEBHOOK_URL en .env")
    headers = {"Content-Type": "application/json", "xapi": os.environ.get("XAPI", "")}  # auth del webhook
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status >= 300:
            raise RuntimeError(f"El webhook respondió {r.status}")


def adjunto(pdf: Path, caption: str = "") -> dict:
    # caption: pie corto para el documento (WhatsApp corta los pies largos); el detalle va en `text`.
    return {"nombre": pdf.name, "mimetype": "application/pdf", "caption": caption,
            "base64": base64.b64encode(pdf.read_bytes()).decode()}


def recortar(texto: str, limite: int = 600) -> str:
    """Corta en el último punto antes del límite, nunca en media palabra."""
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rfind(". ")
    return (texto[:corte + 1] if corte > 0 else texto[:limite].rsplit(" ", 1)[0]) + " …"


def texto_intake(thread_id: str, registro: dict) -> str:
    """El mensaje de WhatsApp: lo justo para decidir sin abrir nada."""
    f, b, p = registro["formulario"], registro.get("borrador"), registro.get("propuesta")
    lineas = [  # *negrita* y _cursiva_ son el formato de WhatsApp
        f"*Nuevo intake* · {p['titulo'] if p else f['tipo']}",
        f"{f['nombre']}" + (f" · {f['empresa']}" if f.get("empresa") else "") + f" · {f['email']}",
        f"Tipo: {f['tipo']} · Plazo: {f['plazo']}",
    ]
    if b:
        lineas.append(f"Encaja: *{'sí' if b['encaja'] else 'no'}* · {b.get('viabilidad', '')}")
        lineas += ["", recortar(b["nota_interna"])]
    else:
        lineas += ["", "Datos insuficientes para proponer. Preguntas para el cliente:"]
        lineas += [f"· {q}" for q in registro.get("preguntas", [])[:5]]
    if registro.get("error"):
        lineas += ["", f"Error al redactar: {registro['error'][:200]}"]
    lineas += ["", f"_Sesión {thread_id}_"]
    return "\n".join(lineas)
