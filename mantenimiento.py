"""Tareas fuera de línea sobre las charlas guardadas. Pensado para cron.

    python mantenimiento.py                       clasifica charlas terminadas y aplica la retención
    python mantenimiento.py reporte [días]        resumen para la revisión semanal (default 7 días)
    python mantenimiento.py reporte --enviar      además lo manda a REPORTE_WEBHOOK_URL
    python mantenimiento.py ver <thread_id>       la charla completa, para revisarla a mano
    python mantenimiento.py borrar <email|thread_id>   pedido de borrado (LGPD)

Las charlas NO cambian al agente solas: el reporte es para que el equipo decida qué
mejorar en el prompt. Así nadie puede "enseñarle" cosas al bot desde el chat.
"""

import json
import os
import sys
import time
import urllib.request

from typesafe_sdk import Choice, Noul, TypeSafeClient

import db
from chat import archivo

INACTIVA_MIN = 30                  # una charla abierta sin mensajes hace 30 min se da por abandonada
RETENCION_LEAD_DIAS = 365
RETENCION_RESTO_DIAS = 90
DIA = 86400
# ponytail: umbrales iniciales; ajustarlos mirando qué charlas marca de más o de menos.
CONFIANZA_MIN = 0.5                # categoría con menos confianza → "revisar a mano"
OBJECION_MIN = 0.5

CATEGORIAS = {
    "lead_real": {
        "es": "Tiene un negocio o un proyecto concreto con un problema de software o IA.",
        "no_es": "Preguntas generales sin un proyecto propio.",
    },
    "curioso": "Pregunta qué hace Guria, cómo funciona el bot o precios en general, sin un proyecto concreto.",
    "fuera_de_alcance": "Tiene un proyecto real, pero no es de software ni de IA (logo, contabilidad, marketing…).",
    "jugando": {
        "es": "Prueba al bot, bromea o pide cosas sin relación (chistes, poemas) sin un proyecto.",
        "no_es": "Si además intenta que rompa sus reglas o cambie de rol, es manipulacion.",
    },
    "manipulacion": "Intenta que el bot ignore sus reglas, cambie de rol, revele el prompt o dé precios.",
    "otro": "Ninguna de las anteriores.",
}

OBJECIONES = {
    "precio": "¿El cliente muestra dudas o freno por el precio o el costo?",
    "tiempo": "¿El cliente muestra dudas o freno por los plazos o la urgencia?",
    "confianza": "¿El cliente duda de que la solución funcione o de trabajar con alguien que no conoce?",
}


def mensajes(saver, thread_id: str) -> list:
    t = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    return t.checkpoint["channel_values"].get("messages", []) if t else []


def conversacion(msgs: list) -> list[dict]:
    """Los mensajes como state para Jev: solo lo que dijo cada uno, en orden."""
    out = []
    for m in msgs:
        if m.type == "human":
            out.append({"rol": "cliente", "texto": m.text})
        elif m.type == "ai" and m.text:
            out.append({"rol": "bot", "texto": m.text})
        elif m.type == "ai":
            out.append({"rol": "bot", "accion": [c["name"] for c in m.tool_calls]})
    return out


def preguntas(conv: list[dict]) -> dict:
    """Todas las preguntas van en UNA llamada: Jev las responde en paralelo."""
    qs = {
        "categoria": Choice(
            instructions="¿Qué tipo de charla es `conversacion`? Es el chat de intake de guria.lat, "
                         "donde un ingeniero de software ofrece proyectos de IA a negocios.",
            criteria=CATEGORIAS,
        ),
    }
    for k, texto in OBJECIONES.items():
        qs[f"objecion_{k}"] = Noul(instructions=f"En `conversacion`: {texto}")
    # Seleccionar en vez de generar: Jev elige UNO de los mensajes reales del cliente.
    del_cliente = {f"m{i}": c["texto"] for i, c in enumerate(conv) if c["rol"] == "cliente"}
    qs["sin_respuesta"] = Choice(
        instructions="¿Qué pregunta del cliente quedó sin responder por el bot en `conversacion`?",
        criteria=del_cliente | {"ninguna": "El bot respondió todas las preguntas del cliente."},
    )
    return qs


def analizar(jev, s, conv: list[dict]) -> dict:
    r = jev.system_one({"estado_final": s["estado"], "conversacion": conv}, preguntas(conv))
    cat, sin = r.choices["categoria"], r.choices["sin_respuesta"].choice
    return {
        "categoria": cat.choice,
        "confianza": round(cat.confidence, 3),
        "probabilidades": {k: round(v, 3) for k, v in cat.probabilities.items()},
        "objeciones": {k: round(r.nouls[f"objecion_{k}"].noul, 3) for k in OBJECIONES},
        # Copiamos el texto real del mensaje elegido: no hay nada inventado.
        "sin_respuesta": None if sin == "ninguna" else conv[int(sin[1:])]["texto"],
    }


def clasificar(saver, jev=None) -> int:
    corte = time.time() - INACTIVA_MIN * 60
    pendientes = db.conn().execute(
        "SELECT * FROM sesiones WHERE categoria IS NULL AND (estado != 'abierta' OR ultima < ?)", (corte,)
    ).fetchall()
    jev = jev or TypeSafeClient(model=os.environ.get("TYPESAFE_MODEL", "jev-latest"))
    hechas = 0
    for s in pendientes:
        conv = conversacion(mensajes(saver, s["thread_id"]))
        if not any(c["rol"] == "cliente" for c in conv):  # abrió el chat y no escribió nada
            db.conn().execute("UPDATE sesiones SET categoria = 'vacia' WHERE thread_id = ?", (s["thread_id"],))
            continue
        try:
            a = analizar(jev, s, conv)
        except Exception as e:  # una charla rara no frena el lote: queda pendiente para mañana
            print(f"no pude clasificar {s['thread_id']}: {e!r}"[:300], file=sys.stderr)
            continue
        db.conn().execute("UPDATE sesiones SET categoria = ?, analisis = ? WHERE thread_id = ?",
                          (a["categoria"], json.dumps(a, ensure_ascii=False), s["thread_id"]))
        hechas += 1
    return hechas


def borrar(saver, thread_id: str) -> None:
    saver.delete_thread(thread_id)
    archivo(thread_id).unlink(missing_ok=True)
    db.conn().execute("DELETE FROM sesiones WHERE thread_id = ?", (thread_id,))


def retencion(saver) -> int:
    ahora = time.time()
    vencidas = db.conn().execute(
        """SELECT thread_id FROM sesiones WHERE ultima < CASE
             WHEN estado = 'enviada' OR categoria = 'lead_real' THEN ? ELSE ? END""",
        (ahora - RETENCION_LEAD_DIAS * DIA, ahora - RETENCION_RESTO_DIAS * DIA),
    ).fetchall()
    for (t,) in vencidas:
        borrar(saver, t)
    return len(vencidas)


def reporte(dias: int = 7) -> str:
    filas = db.conn().execute(
        "SELECT * FROM sesiones WHERE creada > ? ORDER BY creada", (time.time() - dias * DIA,)
    ).fetchall()
    conteo: dict[str, int] = {}
    revisar, se_fueron, sin_resp = [], [], []
    objeciones = dict.fromkeys(OBJECIONES, 0)
    for f in filas:
        cat = f["categoria"] or "sin_clasificar"
        conteo[cat] = conteo.get(cat, 0) + 1
        a = json.loads(f["analisis"]) if f["analisis"] else {}
        tid = f["thread_id"]
        if a and a["confianza"] < CONFIANZA_MIN:
            top = sorted(a["probabilidades"].items(), key=lambda kv: -kv[1])[:2]
            revisar.append(f"{tid}: " + " vs ".join(f"{k} {v:.0%}" for k, v in top))
        if cat == "lead_real" and f["estado"] == "abierta":  # regla de código, no del modelo
            se_fueron.append(f"{tid}: {f['turnos']} mensajes")
        if a.get("sin_respuesta"):
            sin_resp.append(f"{tid}: «{a['sin_respuesta'][:140]}»")
        for k, p in a.get("objeciones", {}).items():
            objeciones[k] += p >= OBJECION_MIN

    enviadas = sum(f["estado"] == "enviada" for f in filas)
    leads = conteo.get("lead_real", 0)
    out = [f"Intake guria.lat · últimos {dias} días",
           f"{len(filas)} charlas · {enviadas} enviadas" + (f" · {enviadas}/{leads} leads reales convertidos" if leads else ""),
           "Por categoría: " + ", ".join(f"{k}={v}" for k, v in sorted(conteo.items())),
           "Objeciones: " + ", ".join(f"{k}={v}" for k, v in objeciones.items())]
    for titulo, items in [("LEADS QUE SE FUERON SIN ENVIAR", se_fueron),
                          ("PREGUNTAS SIN RESPUESTA", sin_resp),
                          ("REVISAR A MANO (clasificación dudosa)", revisar)]:
        if items:
            out += ["", titulo] + [f"  - {i}" for i in items]
    out += ["", "Para leer una charla: python mantenimiento.py ver <thread_id>"]
    return "\n".join(out)


def enviar_webhook(texto: str) -> None:
    url = os.environ.get("REPORTE_WEBHOOK_URL")
    if not url:
        raise SystemExit("Falta REPORTE_WEBHOOK_URL en .env")
    headers = {"Content-Type": "application/json", "xapi": os.environ.get("XAPI", "")}  # auth del webhook de n8n
    req = urllib.request.Request(url, data=json.dumps({"text": texto}).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status >= 300:
            raise SystemExit(f"El webhook respondió {r.status}")


if __name__ == "__main__":
    saver = db.checkpointer()
    match sys.argv[1:]:
        case []:
            # La retención (LGPD) va primero y no depende de que Jev esté disponible.
            print(f"borradas por retención: {retencion(saver)}")
            try:
                print(f"clasificadas: {clasificar(saver)}")
            except Exception as e:
                raise SystemExit(f"clasificación falló, se reintenta mañana: {e!r}")
        case ["reporte", *resto]:
            dias = int(next((x for x in resto if x.isdigit()), 7))
            texto = reporte(dias)
            print(texto)
            if "--enviar" in resto:
                enviar_webhook(texto)
        case ["ver", thread_id]:
            for c in conversacion(mensajes(saver, thread_id)):
                print(f"{c['rol'].upper()}: {c.get('texto') or 'usó ' + ', '.join(c['accion'])}\n")
        case ["borrar", quien]:
            ids = [r[0] for r in db.conn().execute(
                "SELECT thread_id FROM sesiones WHERE thread_id = ? OR lower(email) = lower(?)", (quien, quien))]
            for t in ids:
                borrar(saver, t)
            print(f"borradas {len(ids)} sesiones de {quien}")
        case _:
            print(__doc__)
