"""Workflow que convierte un intake completo en un borrador interno para el equipo
y en una propuesta para el cliente.

El flujo es fijo (StateGraph); el modelo solo trabaja dentro de cada nodo:

    evaluar → triage ─(vaga)→ pedir_datos → END
                     └(ok)──→ buscar ─┬→ redactar ⇄ revisar ─(no encaja)→ END
                                      │                     └(encaja)──→ componer ⇄ revisar_propuesta → END
                                      └→ marketing → END   (en paralelo con redactar)
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from pydantic import BaseModel, Field, ValidationError

import avisos
import deck
import interno
from intake import (SYSTEM, SYSTEM_LECTURA, SYSTEM_PROPUESTA, Borrador, Lectura, Propuesta, buscar_casos,
                    evaluar_encaje, formulario_a_texto)

MAX_INTENTOS = 2


class Triage(BaseModel):
    vaga: bool = Field(description="True si no alcanza para estimar ni con rango amplio.")
    faltantes: list[str] = Field(description="Preguntas concretas para el cliente si es vaga.")


# 1. ESTADO: la "memoria de trabajo" que viaja por el grafo.
# Cada nodo lee lo que necesita y devuelve solo las claves que cambia.
class Estado(TypedDict, total=False):
    formulario: dict
    encaje: dict
    triage: Triage
    casos: list[dict]
    borrador: Borrador
    lectura: Lectura
    problemas: list[str]
    intentos: int
    propuesta: Propuesta
    problemas_propuesta: list[str]
    intentos_propuesta: int


def _modelo():
    return ChatOpenAI(
        base_url=os.environ["ROUTER_BASE_URL"],
        api_key=os.environ["ROUTER_API_KEY"],
        model=os.environ.get("ROUTER_MODEL", "guria-intake"),
        timeout=120,
    )


# 2. NODOS: funciones normales. Reciben el estado, devuelven un dict parcial.
def evaluar(estado: Estado) -> Estado:
    f = estado["formulario"]
    return {"encaje": evaluar_encaje.func(f["plazo"]), "intentos": 0}


def triage(estado: Estado) -> Estado:
    llm = _modelo().with_structured_output(Triage, method="function_calling")
    t = llm.invoke([
        ("system", "Decidí si este formulario de intake alcanza para redactar una estimación."),
        ("user", formulario_a_texto(estado["formulario"])),
    ])
    return {"triage": t}


def pedir_datos(estado: Estado) -> Estado:
    # Sin LLM: el triage ya escribió las preguntas que el equipo le hará al cliente.
    return {"problemas": ["Descripción insuficiente: pedir datos antes de estimar."]}


def buscar(estado: Estado) -> Estado:
    return {"casos": buscar_casos.func(estado["formulario"]["tipo"])}


def redactar(estado: Estado) -> Estado:
    llm = _modelo().with_structured_output(Borrador, method="function_calling")
    contexto = (
        f"{formulario_a_texto(estado['formulario'])}\n\n"
        f"Encaje: {estado['encaje']}\n"
        f"Casos de referencia: {[c['nombre'] + ': ' + c['objetivo'] for c in estado['casos']]}"
    )
    if estado.get("problemas"):  # vuelta del ciclo: el revisor encontró errores
        contexto += f"\n\nTu borrador anterior tenía estos problemas, corregilos: {estado['problemas']}"
    b = llm.invoke([("system", SYSTEM), ("user", contexto)])
    return {"borrador": b, "intentos": estado["intentos"] + 1}


def marketing(estado: Estado) -> Estado:
    # Solo lee el intake, no el borrador: por eso puede correr en paralelo con redactar.
    llm = _modelo().with_structured_output(Lectura, method="function_calling")
    return {"lectura": llm.invoke([("system", SYSTEM_LECTURA),
                                   ("user", formulario_a_texto(estado["formulario"]))])}


def revisar(estado: Estado) -> Estado:
    # Reglas en código, no en el prompt: lo que se puede verificar, se verifica.
    b = estado["borrador"]
    problemas = []
    if not b.esfuerzo:
        problemas.append("Falta el esfuerzo: horas por entregable de la primera etapa.")
    for p in b.esfuerzo:
        if not 0 < p.horas_min <= p.horas_max:
            problemas.append(f"Horas inválidas en '{p.entregable}': mínimo mayor que el máximo o en cero.")
    nombres = {c["nombre"] for c in estado["casos"]}
    if b.caso_relacionado and b.caso_relacionado not in nombres:
        problemas.append(f"caso_relacionado '{b.caso_relacionado}' no existe; usá uno de {sorted(nombres)} o null.")
    if b.viabilidad == "no viable hoy" and b.encaja:
        problemas.append("Dijiste 'no viable hoy' pero encaja true: si no es viable hoy, encaja es false.")
    return {"problemas": problemas}


# 3. ARISTAS CONDICIONALES: funciones que miran el estado y eligen el próximo nodo.
def despues_de_triage(estado: Estado) -> str:
    return "pedir_datos" if estado["triage"].vaga else "buscar"


def despues_de_revisar(estado: Estado) -> str:
    if estado["problemas"] and estado["intentos"] < MAX_INTENTOS:
        return "redactar"
    # Si no es algo que hacemos, no gastamos en una propuesta: el equipo decide con el borrador.
    return "componer" if estado["borrador"].encaja else END


def componer(estado: Estado) -> Estado:
    llm = _modelo().with_structured_output(Propuesta, method="function_calling")
    b = estado["borrador"]
    contexto = (
        f"INTAKE\n{formulario_a_texto(estado['formulario'])}\n\n"
        f"BORRADOR INTERNO (no se lo muestres tal cual al cliente)\n"
        f"Alcance: {b.alcance}\nFuera de alcance: {b.fuera_de_alcance}\nRiesgos: {b.riesgos}\n"
        f"Preguntas abiertas: {b.preguntas_abiertas}\nNota interna: {b.nota_interna}\n"
        f"Viabilidad: {b.viabilidad}. {b.por_que}\nDepende del cliente: {b.depende_del_cliente}\n"
        f"Hipótesis: {b.hipotesis}"
    )
    # marketing corrió en paralelo con redactar, en el mismo paso: acá ya está en el estado.
    if estado.get("lectura"):
        contexto += f"\n\nÁNGULO: {estado['lectura'].angulo}"
    if estado.get("problemas_propuesta"):
        contexto += f"\n\nTu propuesta anterior tenía estos problemas, corregilos: {estado['problemas_propuesta']}"
    p = llm.invoke([("system", SYSTEM_PROPUESTA), ("user", contexto)])
    return {"propuesta": p, "intentos_propuesta": estado.get("intentos_propuesta", 0) + 1}


# Lo que el cliente nunca puede ver, verificado en código y no solo pedido en el prompt.
# "reales"/"reais" también son adjetivos ("turnos reales", "dados reais"): moneda solo junto a un número.
PRECIO = re.compile(r"(US\$|R\$|\$|€|\b(usd|brl)\b|\d\s*(mil\s+)?(dólares?|dolares?|reais|reales)\b)", re.I)
PLAZO = re.compile(r"\b\d+\s*(semanas?|meses|mes|días?|dias?|mês)\b", re.I)
# El límite ético de la lectura, verificado: nada de presión ni escasez inventada.
PRESION = re.compile(r"(últim[oa]s (cupos|lugares|vagas)|s[oó]lo (por )?hoy|s[oó] hoje|descuento|desconto|"
                     r"oferta|promoci[oó]n|promoção|antes de que sea tarde|no te quedes afuera)", re.I)


def textos(p: Propuesta) -> list[str]:
    salida = [p.titulo, p.para, p.lo_que_nos_contaste, p.costo_hoy or ""]
    salida += p.como_se_ve_resuelto + p.lo_que_falta_definir
    for e in p.etapas:
        salida += [e.nombre, e.objetivo, *e.incluye]
    return salida


def revisar_propuesta(estado: Estado) -> Estado:
    p, problemas = estado["propuesta"], []
    todo = "\n".join(textos(p))
    if "—" in todo:
        problemas.append("Hay guiones largos (—). Reemplazalos por dos puntos, coma o punto.")
    if PRECIO.search(todo):
        problemas.append(f"Menciona un precio o una moneda ('{PRECIO.search(todo).group(0)}'). Sacalo: se define en la reunión.")
    if PLAZO.search(todo):
        problemas.append(f"Menciona un plazo ('{PLAZO.search(todo).group(0)}'). Sacalo: se define en la reunión.")
    if PRESION.search(todo):
        problemas.append(f"Presiona al cliente ('{PRESION.search(todo).group(0)}'). Sacalo: sin urgencia ni escasez.")
    if not 2 <= len(p.etapas) <= 3:
        problemas.append("Tienen que ser dos o tres etapas.")
    return {"problemas_propuesta": problemas}


def despues_de_revisar_propuesta(estado: Estado) -> str:
    if estado["problemas_propuesta"] and estado["intentos_propuesta"] < MAX_INTENTOS:
        return "componer"
    return END


# 4. ARMADO: nodos + aristas → compile() da un grafo ejecutable (invoke, stream…).
def build_graph():
    g = StateGraph(Estado)
    g.add_node("evaluar", evaluar)
    # Los modelos a veces omiten un campo obligatorio. LangGraph no reintenta ValidationError
    # por defecto (lo trata como bug), así que se lo pedimos en los nodos que llaman al LLM.
    # Los errores de red ya los reintenta el cliente de OpenAI.
    reintento = RetryPolicy(max_attempts=3, retry_on=ValidationError)
    g.add_node("triage", triage, retry_policy=reintento)
    g.add_node("pedir_datos", pedir_datos)
    g.add_node("buscar", buscar)
    g.add_node("redactar", redactar, retry_policy=reintento)
    g.add_node("revisar", revisar)
    g.add_node("marketing", marketing, retry_policy=reintento)
    g.add_node("componer", componer, retry_policy=reintento)
    g.add_node("revisar_propuesta", revisar_propuesta)

    g.add_edge(START, "evaluar")
    g.add_edge("evaluar", "triage")
    g.add_conditional_edges("triage", despues_de_triage, ["pedir_datos", "buscar"])
    g.add_edge("pedir_datos", END)
    # Dos aristas desde el mismo nodo = fan-out: redactar y marketing corren en el mismo paso.
    g.add_edge("buscar", "redactar")
    g.add_edge("buscar", "marketing")
    g.add_edge("marketing", END)  # termina su rama; el resto del grafo sigue
    g.add_edge("redactar", "revisar")
    g.add_conditional_edges("revisar", despues_de_revisar, ["redactar", "componer", END])
    g.add_edge("componer", "revisar_propuesta")
    g.add_conditional_edges("revisar_propuesta", despues_de_revisar_propuesta, ["componer", END])
    return g.compile()


def resumir(s: Estado) -> dict:
    """Lo que guarda la API: borrador (o null), preguntas y problemas pendientes."""
    return {
        "borrador": s["borrador"].model_dump() if s.get("borrador") else None,
        "preguntas": s["triage"].faltantes if s["triage"].vaga else [],
        "problemas": s.get("problemas", []),
        "intentos": s.get("intentos", 0),
        "lectura": s["lectura"].model_dump() if s.get("lectura") else None,
        "propuesta": s["propuesta"].model_dump() if s.get("propuesta") else None,
        "problemas_propuesta": s.get("problemas_propuesta", []),
    }


def procesar(formulario: dict, graph=None) -> dict:
    return resumir((graph or build_graph()).invoke({"formulario": formulario}))


def _documento(html: str, carpeta: Path, nombre: str) -> Path:
    """Guarda nombre.html y lo pasa a nombre.pdf. Sin Chromium, devuelve el HTML."""
    ruta, pdf = carpeta / f"{nombre}.html", carpeta / f"{nombre}.pdf"
    ruta.write_text(html)
    return pdf if deck.a_pdf(ruta, pdf) else ruta


def completar_borrador(destino: Path, graph=None) -> None:
    """Después de enviar_intake: corre el grafo, arma el documento interno y la propuesta
    (HTML + PDF) y avisa al equipo. Lo usan la API (en segundo plano) y el chat de terminal."""
    log = logging.getLogger("uvicorn.error")
    # El formulario ya está en disco: si algo falla de acá en adelante, el lead no se pierde.
    registro = json.loads(destino.read_text()) | {"error": None}
    try:
        registro |= procesar(registro["formulario"], graph)
    except Exception as e:
        log.exception("intake: falló el grafo")
        registro["error"] = repr(e)

    adjuntos = []
    try:
        if registro.get("borrador"):  # lead.interno.html/.pdf: borrar() los encuentra con lead.*
            adjuntos.append(_documento(interno.render(destino.stem, registro), destino.parent, f"{destino.stem}.interno"))
        if registro.get("propuesta"):
            html = deck.render(Propuesta(**registro["propuesta"]), os.environ.get("AGENDA_URL", "[TU LINK DE AGENDA]"))
            adjuntos.append(_documento(html, destino.parent, destino.stem))
    except Exception as e:
        log.exception("intake: fallaron los documentos")
        registro["error"] = registro["error"] or f"documentos: {e!r}"
    destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2))

    try:  # el aviso va último: si el mail falla, todo lo anterior ya está guardado
        f, p = registro["formulario"], registro.get("propuesta")
        asunto = f"Nuevo intake · {p['titulo'] if p else f['tipo']} · {f['nombre']}"
        avisos.email(asunto, avisos.texto_intake(destino.stem, registro), adjuntos)
    except Exception:
        log.exception("intake: no se pudo mandar el mail")


if __name__ == "__main__":
    import json
    import sys

    from intake import EJEMPLO

    f = EJEMPLO
    if "--vaga" in sys.argv:
        f = {**EJEMPLO, "descripcion": "Quiero una app con inteligencia artificial para mi negocio, algo moderno."}
    # Dos modos a la vez: "updates" dice qué nodo corrió, "values" trae el estado completo.
    for modo, dato in build_graph().stream({"formulario": f}, stream_mode=["updates", "values"]):
        if modo == "updates":
            print("→", ", ".join(dato))
        else:
            final = dato
    print(json.dumps(resumir(final), ensure_ascii=False, indent=2))
