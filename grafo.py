"""Workflow que convierte un intake completo en un borrador interno para Héctor.

El flujo es fijo (StateGraph); el modelo solo trabaja dentro de cada nodo:

    evaluar → triage ─(vaga)→ pedir_datos → END
                     └(ok)──→ buscar_casos → redactar → revisar ─(ok o 2 intentos)→ END
                                                ↑__________________|(problemas)
"""

import os
from typing import TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from intake import SYSTEM, Borrador, buscar_casos, evaluar_encaje, formulario_a_texto

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
    # Sin LLM: el triage ya escribió las preguntas. Héctor se las manda al cliente.
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
    if tope and b.usd_min > tope:
        problemas.append(f"usd_min ({b.usd_min}) supera el presupuesto declarado ({tope}).")
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
    return END


# 4. ARMADO: nodos + aristas → compile() da un grafo ejecutable (invoke, stream…).
def build_graph():
    g = StateGraph(Estado)
    g.add_node("evaluar", evaluar)
    g.add_node("triage", triage)
    g.add_node("pedir_datos", pedir_datos)
    g.add_node("buscar", buscar)
    g.add_node("redactar", redactar)
    g.add_node("revisar", revisar)

    g.add_edge(START, "evaluar")
    g.add_edge("evaluar", "triage")
    g.add_conditional_edges("triage", despues_de_triage, ["pedir_datos", "buscar"])
    g.add_edge("pedir_datos", END)
    g.add_edge("buscar", "redactar")
    g.add_edge("redactar", "revisar")
    g.add_conditional_edges("revisar", despues_de_revisar, ["redactar", END])
    return g.compile()


def resumir(s: Estado) -> dict:
    """Lo que guarda la API: borrador (o null), preguntas y problemas pendientes."""
    return {
        "borrador": s["borrador"].model_dump() if s.get("borrador") else None,
        "preguntas": s["triage"].faltantes if s["triage"].vaga else [],
        "problemas": s.get("problemas", []),
        "intentos": s.get("intentos", 0),
    }


def procesar(formulario: dict, graph=None) -> dict:
    return resumir((graph or build_graph()).invoke({"formulario": formulario}))


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
