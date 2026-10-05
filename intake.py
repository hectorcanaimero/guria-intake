"""Dominio del intake: casos de referencia, reglas de encaje, el borrador interno,
la propuesta para el cliente y los prompts con que se escriben."""

import math
import os
from typing import Literal

from langchain.tools import tool
from pydantic import BaseModel, Field

# Proyectos publicados en guria.lat. El agente los usa como referencia, no los inventa.
CASOS = [
    {"nombre": "PideAI", "tipos": ["whatsapp", "agentes"], "objetivo": "Pedidos por WhatsApp para restaurantes y tiendas, con agente que agenda vía function calling.", "stack": "NestJS · FastAPI · pgvector · Flutter"},
    {"nombre": "Showly", "tipos": ["showly", "whatsapp"], "objetivo": "Agenda por WhatsApp para clínicas: recordatorios y confirmación para bajar no-shows.", "stack": "NestJS · Next.js · Prisma · pgvector · BullMQ"},
    {"nombre": "Orch", "tipos": ["agentes", "infra"], "objetivo": "Agentes de código en paralelo sobre un grafo de tareas, con control de cuota por proveedor.", "stack": "Go · SQLite"},
    {"nombre": "Open Fluent", "tipos": ["agentes"], "objetivo": "Gate de evaluación: un modelo entra a producción solo con ≥95 % JSON válido y p90 < 8 s.", "stack": "TypeScript · evaluación offline"},
    {"nombre": "UseBot", "tipos": ["agentes", "producto"], "objetivo": "Chatbot RAG sobre documentos del negocio, corriendo en Cloudflare.", "stack": "Cloudflare Workers · Vectorize · Workers AI"},
    {"nombre": "Blog con agentes", "tipos": ["agentes", "producto"], "objetivo": "Tres agentes escriben, optimizan e ilustran contenido para una cadena de supermercados.", "stack": "Next.js · Claude · prompts versionados en BD"},
    {"nombre": "Labo System", "tipos": ["producto"], "objetivo": "Administración de laboratorio clínico con informes PDF desde plantillas.", "stack": "Next.js · Convex · react-pdf"},
    {"nombre": "Squads en infra propia", "tipos": ["infra", "agentes"], "objetivo": "Orquestación de agentes en servidores propios: 3× paralelo real.", "stack": "Multica · Ollama · OpenRouter · VPS"},
]

@tool
def buscar_casos(tipo: str) -> list[dict]:
    """Devuelve los proyectos del equipo que sirven de referencia para un tipo de
    proyecto (producto, agentes, whatsapp, showly, infra, otro). Lista vacía si ninguno sirve:
    mejor sin referencia que con una forzada."""
    return [c for c in CASOS if tipo in c["tipos"]]


@tool
def evaluar_encaje(plazo: str) -> dict:
    """Señales deterministas sobre el plazo. Usala antes de estimar.
    Sin presupuesto a propósito: al cliente no se le pregunta, y así no ancla la estimación."""
    alertas = []
    if plazo == "Esta semana":
        alertas.append("Plazo urgente: confirmar si es una emergencia en producción.")
    return {"alertas": alertas}


class Partida(BaseModel):
    entregable: str = Field(description="Un entregable de la primera etapa, en pocas palabras.")
    horas_min: int = Field(description="Horas de trabajo si todo sale bien.")
    horas_max: int = Field(description="Horas si aparecen los problemas de siempre (accesos, aprobaciones, ajustes).")


class Borrador(BaseModel):
    resumen: str = Field(description="El problema del cliente en 2-3 frases, en sus términos.")
    alcance: list[str] = Field(description="Entregables concretos de la primera etapa.")
    fuera_de_alcance: list[str] = Field(description="Lo que explícitamente NO entra.")
    riesgos: list[str] = Field(description="Riesgos técnicos o de negocio, con la mitigación.")
    esfuerzo: list[Partida] = Field(description="Horas por entregable de la primera etapa. La plata y las semanas las calcula el código.")
    caso_relacionado: str | None = Field(description="Nombre de un caso de buscar_casos, o null.")
    preguntas_abiertas: list[str] = Field(description="Lo que falta saber para cerrar la propuesta.")
    encaja: bool = Field(description="Si el proyecto encaja con lo que hace el equipo.")
    viabilidad: Literal["viable", "viable con condiciones", "no viable hoy"]
    por_que: str = Field(description="Por qué esa viabilidad, en 2 o 3 frases sin jerga.")
    enfoque_tecnico: str = Field(description="Una línea: cómo se resolvería, por ejemplo 'agente sobre WhatsApp Cloud API + su planilla'.")
    reusar_antes_de_construir: list[str] = Field(description="Lo que ya existe (SaaS, n8n, una API) y ahorra código.")
    depende_del_cliente: list[str] = Field(description="Lo que tiene que poner el cliente: accesos, datos, aprobaciones, una persona de su lado.")
    hipotesis: str = Field(description="Lo que tiene que ser cierto para que el proyecto valga la pena.")
    como_sabremos: str = Field(description="La métrica que dice si la primera etapa funcionó.")
    nota_interna: str = Field(description="Comentario para el equipo, no para el cliente.")


SYSTEM = """Sos el Product Owner con criterio técnico de guria.lat, un equipo que lleva \
IA a producción para negocios de Brasil y LATAM. Preparás el borrador INTERNO de un intake: \
el equipo lo lee antes de la reunión con el cliente; nunca le hablás al cliente directamente.

Recibís el formulario, alertas sobre el plazo y los casos de referencia del equipo.

Tu trabajo es decidir si se puede, con qué condiciones y cuál es el paso más chico que lo \
prueba. No escribas un SPEC ni un PRD: nada de endpoints, diagramas, modelos de datos ni \
listas de tecnologías. El enfoque técnico entra en una línea.

Reglas:
- Antes de proponer construir, buscá qué ya existe y lo resuelve (un SaaS, n8n, una API).
- viabilidad "no viable hoy" significa encaja false. Si es "viable con condiciones", las \
condiciones van en depende_del_cliente o en riesgos.
- hipotesis y como_sabremos: concretas y medibles, con los números del cliente si los dio.
- Si la descripción es vaga, no inventes requisitos: estimá con rango amplio y \
poné las dudas en preguntas_abiertas.
- Estimá horas por entregable, no plata ni semanas: eso lo calcula el código con la \
tarifa del equipo. No escribas montos en ningún campo.
- Estimá lo que el proyecto lleva de verdad. Proponé una primera etapa chica que \
pruebe valor antes de invertir más (por ejemplo, validar la idea antes de construir).
- caso_relacionado: como mucho uno, y solo de los casos de referencia. Puede no haber ninguno.
- encaja: si es trabajo que hace el equipo (IA, agentes, WhatsApp, productos de punta a \
punta, infraestructura). No depende de que haya un caso parecido.
- Escribí en el idioma del formulario (español o portugués)."""


class Lectura(BaseModel):
    """Lectura del cliente para preparar la reunión. Interna: el cliente nunca la ve."""
    dolor_real: str = Field(description="Lo que de verdad le duele, que puede no ser lo que pidió. 1 o 2 frases.")
    que_lo_mueve: list[str] = Field(description="Dos o tres motivos por los que decidiría: ahorrar, crecer, no quedarse atrás, sacarse un peso.")
    objeciones: list[str] = Field(description="Dos o tres objeciones probables, cada una con cómo responderla: 'objeción → respuesta'.")
    angulo: str = Field(description="Cómo encuadrar la propuesta en una frase, por ejemplo desde lo que pierde hoy.")
    abrir_la_reunion: str = Field(description="La primera pregunta para la reunión, abierta, sobre su problema.")


SYSTEM_LECTURA = """Leés un intake de guria.lat con ojo de marketing y psicología del \
comprador para que el equipo prepare la reunión. No le hablás al cliente.

Usá lo que sabemos de cómo decide la gente: el costo de lo que pierde hoy pesa más que \
lo que ganaría, prefiere empezar chico y sin riesgo, y confía en lo concreto. Basate solo \
en lo que dijo el cliente: no inventes datos sobre él ni sobre su empresa.

Límite ético: esto es para entenderlo y ayudarlo a decidir bien, no para presionarlo. \
Nada de urgencia falsa, escasez inventada, descuentos por tiempo limitado ni miedo.

Escribí en el idioma del formulario (español o portugués)."""


# Tarifa freelance senior para clientes LATAM (no nearshore a EE. UU., que paga casi el doble).
# Brasil 2026: R$ 120–280/h senior, R$ 140–220/h especialista en IA como PJ ≈ USD 25–45.
# Fuentes: lancei.pro/benchmark/desenvolvedor-backend, blog.beerandcode.com.br (engenheiro de IA 2026).
# Se ajusta en .env sin tocar código: TARIFA_USD_HORA="25-45", HORAS_SEMANA="25".
def estimar(esfuerzo: list[dict]) -> dict:
    """Horas del modelo × tarifa del equipo. El modelo nunca pone el precio."""
    t_min, t_max = (int(x) for x in os.environ.get("TARIFA_USD_HORA", "25-45").split("-"))
    por_semana = int(os.environ.get("HORAS_SEMANA", "25"))
    h_min = sum(p["horas_min"] for p in esfuerzo)
    h_max = sum(p["horas_max"] for p in esfuerzo)
    return {"horas": (h_min, h_max), "usd": (h_min * t_min, h_max * t_max), "tarifa": (t_min, t_max),
            "semanas": (max(1, math.ceil(h_min / por_semana)), max(1, math.ceil(h_max / por_semana)))}


def formulario_a_texto(f: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in f.items() if v)


EJEMPLO = {
    "nombre": "Marina",
    "empresa": "Clínica Sorriso",
    "tipo": "whatsapp",
    "descripcion": "Tenemos 3 dentistas y perdemos muchos turnos porque los pacientes no confirman. Hoy la recepcionista llama uno por uno.",
    "plazo": "Este mes",
}


# ── Propuesta para el cliente ────────────────────────────────────────────────
# Esquema distinto del Borrador a propósito: acá no existe ningún campo de precio
# ni de plazo, así que el modelo no tiene dónde poner uno.

class Etapa(BaseModel):
    nombre: str = Field(description="Nombre de la etapa en 2 a 5 palabras, por ejemplo 'Validar con 20 prestadores'.")
    objetivo: str = Field(description="Qué se aprende o se logra al terminarla, en una frase.")
    incluye: list[str] = Field(description="Dos o tres entregables concretos, de hasta 8 palabras cada uno.")


class Propuesta(BaseModel):
    idioma: Literal["es", "pt"] = Field(description="Idioma del cliente.")
    titulo: str = Field(description="Nombre del proyecto en 2 a 6 palabras, sin adjetivos de marketing.")
    para: str = Field(description="Nombre del cliente y, si la hay, su empresa.")
    lo_que_nos_contaste: str = Field(description="El problema con las palabras del cliente, 2 a 4 frases.")
    costo_hoy: str | None = Field(None, description="Lo que le cuesta hoy el problema, SOLO con números que dio el cliente. Null si no dio ninguno.")
    como_se_ve_resuelto: list[str] = Field(description="Tres o cuatro frases sobre un día normal con el problema resuelto.")
    etapas: list[Etapa] = Field(description="Dos o tres etapas. La primera, chica: lo mínimo que prueba que funciona.")
    lo_que_falta_definir: list[str] = Field(description="Las tres preguntas que más cambian el alcance, para la reunión.")


SYSTEM_PROPUESTA = """Escribís la propuesta que guria.lat le va a mostrar a un posible cliente, \
a partir de su intake y del borrador interno del equipo. El objetivo de la propuesta es \
que el cliente quiera agendar una reunión online de 30 minutos para ajustarla juntos.

Reglas de escritura (obligatorias):
- Si te paso un ángulo, usalo para ordenar el relato, sin nombrarlo ni exagerarlo.
- Español rioplatense con voseo, o portugués de Brasil si el cliente escribió en portugués.
- Frases cortas, sujeto y verbo. Nada de "soluciones innovadoras", "transformación digital" \
ni frases intercambiables entre empresas.
- Nunca uses guión largo. Usá dos puntos, coma o punto.
- Nunca inventes métricas, clientes, testimonios ni fechas.
- Ningún precio, monto, moneda ni plazo en semanas, meses o días: eso se define en la reunión.
- lo_que_nos_contaste usa las palabras del cliente, no las tuyas.
- costo_hoy solo si el cliente dio números; si no, null.
- Las etapas no prometen resultados: dicen qué se construye y qué se aprende.
- No menciones proyectos anteriores del equipo: la propuesta habla solo del cliente."""
