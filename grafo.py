"""Workflow que convierte un intake completo en un borrador interno para el equipo
y en una propuesta para el cliente.

El flujo es fijo (StateGraph); el modelo solo trabaja dentro de cada nodo:

    evaluar → triage ─(vaga)→ pedir_datos → END
                     └(ok)──→ buscar → redactar ⇄ revisar → componer ⇄ revisar_propuesta → END
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
from intake import (CASOS, SYSTEM, SYSTEM_PROPUESTA, Borrador, Propuesta, buscar_casos,
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
    return {"encaje": evaluar_encaje.func(f["presupuesto"], f["plazo"]), "intentos": 0}


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


def revisar(estado: Estado) -> Estado:
    # Reglas en código, no en el prompt: lo que se puede verificar, se verifica.
    b, tope = estado["borrador"], estado["encaje"]["tope_usd"]
    problemas = []
    if b.semanas_min > b.semanas_max or b.usd_min > b.usd_max:
        problemas.append("Rango invertido: el mínimo es mayor que el máximo.")
    # Sin regla de presupuesto: forzar que la estimación "entre" premia mentir.
    # Si no entra, el prompt pide decirlo en nota_interna y proponer una etapa menor.
    nombres = {c["nombre"] for c in estado["casos"]}
    if b.caso_relacionado and b.caso_relacionado not in nombres:
        problemas.append(f"caso_relacionado '{b.caso_relacionado}' no existe; usá uno de {sorted(nombres)} o null.")
    return {"problemas": problemas}


# 3. ARISTAS CONDICIONALES: funciones que miran el estado y eligen el próximo nodo.
def despues_de_triage(estado: Estado) -> str:
    return "pedir_datos" if estado["triage"].vaga else "buscar"


def despues_de_revisar(estado: Estado) -> str:
    if estado["problemas"] and estado["intentos"] < MAX_INTENTOS:
        return "redactar"
    return "componer"


def componer(estado: Estado) -> Estado:
    llm = _modelo().with_structured_output(Propuesta, method="function_calling")
    b = estado["borrador"]
    contexto = (
        f"INTAKE\n{formulario_a_texto(estado['formulario'])}\n\n"
        f"BORRADOR INTERNO (no se lo muestres tal cual al cliente)\n"
        f"Alcance: {b.alcance}\nFuera de alcance: {b.fuera_de_alcance}\nRiesgos: {b.riesgos}\n"
        f"Preguntas abiertas: {b.preguntas_abiertas}\nNota interna: {b.nota_interna}\n\n"
        f"CASOS DE REFERENCIA: {[c['nombre'] + ': ' + c['objetivo'] for c in CASOS]}"
    )
    if estado.get("problemas_propuesta"):
        contexto += f"\n\nTu propuesta anterior tenía estos problemas, corregilos: {estado['problemas_propuesta']}"
    p = llm.invoke([("system", SYSTEM_PROPUESTA), ("user", contexto)])
    return {"propuesta": p, "intentos_propuesta": estado.get("intentos_propuesta", 0) + 1}


# Lo que el cliente nunca puede ver, verificado en código y no solo pedido en el prompt.
PRECIO = re.compile(r"(US\$|R\$|\$|€|\b(usd|brl|dólares?|dolares?|reais|reales)\b)", re.I)
PLAZO = re.compile(r"\b\d+\s*(semanas?|meses|mes|días?|dias?|mês)\b", re.I)


def textos(p: Propuesta) -> list[str]:
    salida = [p.titulo, p.para, p.lo_que_nos_contaste, p.costo_hoy or "", p.por_que_el_caso or ""]
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
    if p.caso and p.caso not in {c["nombre"] for c in CASOS}:
        problemas.append(f"El caso '{p.caso}' no existe. Usá un nombre exacto de la lista o null.")
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
    g.add_node("componer", componer, retry_policy=reintento)
    g.add_node("revisar_propuesta", revisar_propuesta)

    g.add_edge(START, "evaluar")
    g.add_edge("evaluar", "triage")
    g.add_conditional_edges("triage", despues_de_triage, ["pedir_datos", "buscar"])
    g.add_edge("pedir_datos", END)
    g.add_edge("buscar", "redactar")
    g.add_edge("redactar", "revisar")
    g.add_conditional_edges("revisar", despues_de_revisar, ["redactar", "componer"])
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
        "propuesta": s["propuesta"].model_dump() if s.get("propuesta") else None,
        "problemas_propuesta": s.get("problemas_propuesta", []),
    }


def procesar(formulario: dict, graph=None) -> dict:
    return resumir((graph or build_graph()).invoke({"formulario": formulario}))


def completar_borrador(destino: Path, graph=None) -> None:
    """Después de enviar_intake: redacta, arma la propuesta (HTML + PDF) y avisa al equipo.
    Lo usan la API (en segundo plano) y el chat de terminal."""
    log = logging.getLogger("uvicorn.error")
    # El formulario ya está en disco: si algo falla de acá en adelante, el lead no se pierde.
    registro = json.loads(destino.read_text()) | {"error": None}
    try:
        registro |= procesar(registro["formulario"], graph)
    except Exception as e:
        log.exception("intake: falló el grafo")
        registro["error"] = repr(e)

    pdf = None
    if registro.get("propuesta"):
        try:
            html = destino.with_suffix(".html")
            html.write_text(deck.render(Propuesta(**registro["propuesta"]),
                                        os.environ.get("AGENDA_URL", "[TU LINK DE AGENDA]")))
            pdf = destino.with_suffix(".pdf") if deck.a_pdf(html, destino.with_suffix(".pdf")) else None
        except Exception as e:
            log.exception("intake: falló el deck")
            registro["error"] = registro["error"] or f"deck: {e!r}"
    destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2))

    try:  # el aviso va último: si el webhook falla, todo lo anterior ya está guardado
        payload = {"tipo": "nuevo_intake", "text": avisos.texto_intake(destino.stem, registro)}
        if pdf:
            payload["archivo"] = avisos.adjunto(pdf, f"Propuesta · {registro['propuesta']['titulo']}")
        avisos.enviar(payload)
    except Exception:
        log.exception("intake: no se pudo avisar por el webhook")


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
