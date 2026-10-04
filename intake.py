"""Dominio del intake: casos de referencia, reglas de encaje, el esquema del
borrador interno y el prompt con el que se redacta."""

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
    """Devuelve los proyectos de Héctor que sirven de referencia para un tipo de
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
    preguntas_abiertas: list[str] = Field(description="Lo que falta saber para cerrar la estimación.")
    encaja: bool = Field(description="Si el proyecto encaja con lo que Héctor hace.")
    nota_interna: str = Field(description="Comentario para Héctor, no para el cliente.")


SYSTEM = """Sos el asistente de intake de Héctor Rodríguez (guria.lat), ingeniero de \
software sénior que lleva IA a producción para negocios de Brasil y LATAM.

Recibís un formulario de un posible cliente. Redactá un BORRADOR que Héctor va a \
revisar antes de enviar; nunca le hablás al cliente directamente.

Proceso:
1. Llamá a evaluar_encaje con el presupuesto y el plazo.
2. Llamá a buscar_casos con el tipo de proyecto y elegí como mucho un caso relacionado.
3. Devolvé el Borrador.

Reglas:
- Si la descripción es vaga, no inventes requisitos: estimá con rango amplio y \
poné las dudas en preguntas_abiertas.
- La estimación tiene que respetar el presupuesto declarado o decir en nota_interna \
por qué no entra.
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
