"""Dominio del intake: casos de referencia, reglas de encaje, el borrador interno,
la propuesta para el cliente y los prompts con que se escriben."""

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

PRESUPUESTO_MAX_USD = {
    "Menos de USD 2.000": 2000,
    "USD 2.000 a 5.000": 5000,
    "USD 5.000 a 15.000": 15000,
    "Más de USD 15.000": None,
    "Todavía no sé": None,
}


@tool
def buscar_casos(tipo: str) -> list[dict]:
    """Devuelve los proyectos del equipo que sirven de referencia para un tipo de
    proyecto (producto, agentes, whatsapp, showly, infra, otro)."""
    return [c for c in CASOS if tipo in c["tipos"]] or CASOS


@tool
def evaluar_encaje(presupuesto: str, plazo: str) -> dict:
    """Señales deterministas sobre presupuesto y plazo. Usala antes de estimar."""
    tope = PRESUPUESTO_MAX_USD.get(presupuesto)
    alertas = []
    if tope is not None and tope <= 2000:
        alertas.append("Presupuesto bajo: proponer un MVP muy acotado o un piloto.")
    if plazo == "Esta semana":
        alertas.append("Plazo urgente: confirmar si es una emergencia en producción.")
    if presupuesto == "Todavía no sé":
        alertas.append("Sin presupuesto: dar dos o tres opciones con rango de precio.")
    return {"tope_usd": tope, "alertas": alertas}


class Borrador(BaseModel):
    resumen: str = Field(description="El problema del cliente en 2-3 frases, en sus términos.")
    alcance: list[str] = Field(description="Entregables concretos de la primera etapa.")
    fuera_de_alcance: list[str] = Field(description="Lo que explícitamente NO entra.")
    riesgos: list[str] = Field(description="Riesgos técnicos o de negocio, con la mitigación.")
    semanas_min: int
    semanas_max: int
    usd_min: int
    usd_max: int
    caso_relacionado: str | None = Field(description="Nombre de un caso de buscar_casos, o null.")
    preguntas_abiertas: list[str] = Field(description="Lo que falta saber para cerrar la propuesta.")
    encaja: bool = Field(description="Si el proyecto encaja con lo que hace el equipo.")
    nota_interna: str = Field(description="Comentario para el equipo, no para el cliente.")


SYSTEM = """Preparás el borrador INTERNO de un intake de guria.lat, un equipo que lleva \
IA a producción para negocios de Brasil y LATAM. El equipo lo lee antes de la reunión \
con el cliente; nunca le hablás al cliente directamente.

Recibís el formulario, el encaje con el presupuesto y los casos de referencia del equipo.

Reglas:
- Si la descripción es vaga, no inventes requisitos: estimá con rango amplio y \
poné las dudas en preguntas_abiertas.
- Estimá lo que el proyecto cuesta de verdad, aunque no entre en el presupuesto \
declarado. No achiques la estimación para que entre: si no entra, decilo en \
nota_interna y proponé una primera etapa más chica que sí entre (por ejemplo, \
validar la idea antes de construir).
- caso_relacionado: como mucho uno, y solo de los casos de referencia.
- Escribí en el idioma del formulario (español o portugués)."""


def formulario_a_texto(f: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in f.items() if v)


EJEMPLO = {
    "nombre": "Marina",
    "empresa": "Clínica Sorriso",
    "tipo": "whatsapp",
    "descripcion": "Tenemos 3 dentistas y perdemos muchos turnos porque los pacientes no confirman. Hoy la recepcionista llama uno por uno.",
    "presupuesto": "USD 2.000 a 5.000",
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
    caso: str | None = Field(None, description="Nombre EXACTO de un caso de referencia que se parezca de verdad, o null.")
    por_que_el_caso: str | None = Field(None, description="Una frase: en qué se parece ese caso al del cliente.")
    etapas: list[Etapa] = Field(description="Dos o tres etapas. La primera, chica y alcanzable con su presupuesto.")
    lo_que_falta_definir: list[str] = Field(description="Las tres preguntas que más cambian el alcance, para la reunión.")


SYSTEM_PROPUESTA = """Escribís la propuesta que guria.lat le va a mostrar a un posible cliente, \
a partir de su intake y del borrador interno del equipo. El objetivo de la propuesta es \
que el cliente quiera agendar una reunión online de 30 minutos para ajustarla juntos.

Reglas de escritura (obligatorias):
- Español rioplatense con voseo, o portugués de Brasil si el cliente escribió en portugués.
- Frases cortas, sujeto y verbo. Nada de "soluciones innovadoras", "transformación digital" \
ni frases intercambiables entre empresas.
- Nunca uses guión largo. Usá dos puntos, coma o punto.
- Nunca inventes métricas, clientes, testimonios ni fechas.
- Ningún precio, monto, moneda ni plazo en semanas, meses o días: eso se define en la reunión.
- lo_que_nos_contaste usa las palabras del cliente, no las tuyas.
- costo_hoy solo si el cliente dio números; si no, null.
- Las etapas no prometen resultados: dicen qué se construye y qué se aprende. Si el \
borrador interno dice que el presupuesto no alcanza, la primera etapa es la chica que sí entra.
- caso: solo uno de los casos de referencia que te paso, con su nombre exacto, y solo si se \
parece de verdad. Si ninguno se parece, null."""
