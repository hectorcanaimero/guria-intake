"""Avisos al equipo.

- Cada intake llega por email, con el documento interno y la propuesta adjuntos.
- El reporte semanal sigue por el webhook de n8n (que lo reenvía por WhatsApp).
"""

import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage
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


def email(asunto: str, texto: str, adjuntos: list[Path]) -> None:
    """Manda un mail por SMTP (stdlib). Puerto 465 = SSL directo; cualquier otro, STARTTLS."""
    falta = [v for v in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM", "AVISOS_EMAIL") if not os.environ.get(v)]
    if falta:
        raise RuntimeError(f"Faltan {', '.join(falta)} en .env")
    msg = EmailMessage()
    msg["Subject"], msg["To"] = asunto, os.environ["AVISOS_EMAIL"]
    msg["From"] = os.environ["SMTP_FROM"]  # en Resend, de un dominio verificado
    msg.set_content(texto)
    for f in adjuntos:
        tipo = ("application", "pdf") if f.suffix == ".pdf" else ("text", "html")
        msg.add_attachment(f.read_bytes(), maintype=tipo[0], subtype=tipo[1], filename=f.name)

    host, puerto = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465"))
    conexion = smtplib.SMTP_SSL if puerto == 465 else smtplib.SMTP
    with conexion(host, puerto, timeout=30) as s:
        if puerto != 465:
            s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.send_message(msg)


def recortar(texto: str, limite: int = 600) -> str:
    """Corta en el último punto antes del límite, nunca en media palabra."""
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rfind(". ")
    return (texto[:corte + 1] if corte > 0 else texto[:limite].rsplit(" ", 1)[0]) + " …"


def texto_intake(thread_id: str, registro: dict) -> str:
    """El cuerpo del mail: lo justo para decidir sin abrir los adjuntos."""
    f, b, p = registro["formulario"], registro.get("borrador"), registro.get("propuesta")
    lineas = [
        f"Nuevo intake · {p['titulo'] if p else f['tipo']}",
        f"{f['nombre']}" + (f" · {f['empresa']}" if f.get("empresa") else "") + f" · {f['email']}",
        f"Tipo: {f['tipo']} · Plazo: {f['plazo']}",
    ]
    if b:
        lineas.append(f"Encaja: {'sí' if b['encaja'] else 'no'} · {b.get('viabilidad', '')}")
        lineas += ["", recortar(b["nota_interna"])]
    else:
        lineas += ["", "Datos insuficientes para proponer. Preguntas para el cliente:"]
        lineas += [f"· {q}" for q in registro.get("preguntas", [])[:5]]
    if registro.get("error"):
        lineas += ["", f"Error al redactar: {registro['error'][:200]}"]
    if p:
        lineas += ["", "Adjuntos: el documento interno (no reenviar) y la propuesta para el cliente (revisala antes de reenviarla)."]
    lineas += ["", f"Sesión {thread_id}"]
    return "\n".join(lineas)
