"""Documento interno del intake en A4: el borrador del Product Owner y la lectura del
cliente, para preparar la reunión. Nunca va al cliente; por eso sí lleva estimación.

Igual que deck.py: el modelo escribe el contenido y este archivo pone el formato.
"""

from datetime import date
from html import escape as e

from deck import logo
from intake import estimar

CSS = """
@page { size: A4; margin: 18mm 16mm; }
:root { --ink:#111417; --soft:#35383B; --muted:#63635B; --rule:#C9C7BE; --signal:#B03A1B; --sunk:#F2F1EC;
  --display:"Archivo","Helvetica Neue",Arial,sans-serif; --body:"Newsreader",Georgia,serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--body); color: var(--ink); font-size: 11.5pt; line-height: 1.45;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
@media screen { body { max-width: 760px; margin: 32px auto; padding: 0 16px; } }
header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 10px;
  border-bottom: 2px solid var(--ink); font-family: var(--mono); font-size: 8.5pt; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted); }
header b { font-family: var(--display); font-size: 13pt; letter-spacing: -.02em; text-transform: none; color: var(--ink); }
h1 { font-family: var(--display); font-size: 24pt; letter-spacing: -.03em; line-height: 1.1; margin: 18px 0 4px; }
.para { color: var(--soft); margin-bottom: 14px; }
.veredicto { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.chip { font-family: var(--mono); font-size: 8.5pt; letter-spacing: .06em; text-transform: uppercase;
  border: 1px solid var(--ink); padding: 4px 8px; }
.chip.alerta { background: var(--signal); border-color: var(--signal); color: #fff; }
h2 { font-family: var(--mono); font-size: 8.5pt; letter-spacing: .14em; text-transform: uppercase;
  color: var(--signal); margin: 18px 0 6px; padding-top: 10px; border-top: 1px solid var(--rule); }
p + p { margin-top: 6px; }
ul { padding-left: 16px; } li + li { margin-top: 3px; }
dl { display: grid; grid-template-columns: 150px 1fr; gap: 4px 12px; }
small { font-size: 9pt; color: var(--muted); }
dt { font-family: var(--mono); font-size: 8.5pt; color: var(--muted); padding-top: 2px; }
.nota { background: var(--sunk); padding: 10px 12px; border-left: 3px solid var(--signal); }
h2, dt { break-after: avoid; } li, dd { break-inside: avoid; }
"""


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _lista(xs: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{e(x)}</li>" for x in xs) + "</ul>" if xs else "<p>—</p>"


def render(thread_id: str, registro: dict, hoy: date | None = None) -> str:
    f, b, l = registro["formulario"], registro["borrador"], registro.get("lectura")
    p = registro.get("propuesta")
    titulo = p["titulo"] if p else f["tipo"].capitalize()
    cliente = f["nombre"] + (f" · {f['empresa']}" if f.get("empresa") else "") + f" · {f['email']}"
    alerta = "" if b["viabilidad"] == "viable" else " alerta"
    est = estimar(b["esfuerzo"])
    horas = "".join(f"<li>{e(p['entregable'])}: {p['horas_min']}–{p['horas_max']} h</li>" for p in b["esfuerzo"])

    s = [f'<header><span style="display:flex;gap:8px;align-items:center">{logo("#111417", "#E2502B", 18)}'
         f'<b>guria.lat</b></span><span>Interno · {(hoy or date.today()).isoformat()} · {e(thread_id)}</span></header>',
         f"<h1>{e(titulo)}</h1><p class='para'>{e(cliente)}</p>",
         f'<div class="veredicto"><span class="chip{alerta}">{e(b["viabilidad"])}</span>'
         f'<span class="chip">encaja: {"sí" if b["encaja"] else "no"}</span>'
         f'<span class="chip">{e(f["plazo"])}</span></div>',
         f"<section><h2>El problema</h2><p>{e(b['resumen'])}</p></section>",
         f"<section><h2>Viabilidad</h2><p>{e(b['por_que'])}</p><dl>"
         f"<dt>Enfoque</dt><dd>{e(b['enfoque_tecnico'])}</dd>"
         f"<dt>Reusar antes de construir</dt><dd>{_lista(b['reusar_antes_de_construir'])}</dd>"
         f"<dt>Depende del cliente</dt><dd>{_lista(b['depende_del_cliente'])}</dd>"
         f"<dt>Hipótesis</dt><dd>{e(b['hipotesis'])}</dd>"
         f"<dt>Cómo sabremos</dt><dd>{e(b['como_sabremos'])}</dd></dl></section>",
         f"<section><h2>Primera etapa</h2><dl><dt>Incluye</dt><dd>{_lista(b['alcance'])}</dd>"
         f"<dt>No incluye</dt><dd>{_lista(b['fuera_de_alcance'])}</dd>"
         f"<dt>Esfuerzo</dt><dd><ul>{horas}</ul></dd>"
         f"<dt>Estimación</dt><dd><b>USD {_miles(est['usd'][0])}–{_miles(est['usd'][1])}</b> · "
         f"{est['horas'][0]}–{est['horas'][1]} h · {est['semanas'][0]}–{est['semanas'][1]} semanas<br>"
         f"<small>Tarifa de referencia USD {est['tarifa'][0]}–{est['tarifa'][1]}/h, freelance senior para clientes LATAM</small></dd>"
         + (f"<dt>Caso parecido</dt><dd>{e(b['caso_relacionado'])}</dd>" if b.get("caso_relacionado") else "")
         + "</dl></section>",
         f"<section><h2>Riesgos</h2>{_lista(b['riesgos'])}</section>"]
    if l:
        s.append(f"<section><h2>Lectura del cliente</h2><dl>"
                 f"<dt>Dolor real</dt><dd>{e(l['dolor_real'])}</dd>"
                 f"<dt>Qué lo mueve</dt><dd>{_lista(l['que_lo_mueve'])}</dd>"
                 f"<dt>Objeciones</dt><dd>{_lista(l['objeciones'])}</dd>"
                 f"<dt>Ángulo</dt><dd>{e(l['angulo'])}</dd>"
                 f"<dt>Abrir la reunión</dt><dd>{e(l['abrir_la_reunion'])}</dd></dl></section>")
    s.append(f"<section><h2>Preguntas abiertas</h2>{_lista(b['preguntas_abiertas'])}</section>")
    s.append(f"<section><h2>Nota interna</h2><p class='nota'>{e(b['nota_interna'])}</p></section>")
    if registro.get("problemas"):  # el revisor no quedó conforme después de los reintentos
        s.append(f"<section><h2>Sin resolver por el revisor</h2>{_lista(registro['problemas'])}</section>")

    fuentes = ("https://fonts.googleapis.com/css2?family=Archivo:wght@600;800"
               "&family=Newsreader:opsz,wght@6..72,400&family=JetBrains+Mono:wght@400&display=swap")
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Interno · {e(titulo)}</title>'
            f'<link rel="stylesheet" href="{fuentes}"><style>{CSS}</style></head><body>{"".join(s)}</body></html>')
