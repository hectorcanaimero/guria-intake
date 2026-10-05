"""Convierte una Propuesta en slides HTML con el diseño de guria.lat, y en PDF.

El modelo solo escribe el contenido (intake.Propuesta). El diseño y el llamado a la reunión los pone este archivo: así todas las propuestas
salen iguales y el modelo no puede romper el layout ni colar un precio.
"""

import glob
import os
import shutil
import subprocess
from datetime import date
from html import escape
from pathlib import Path

from intake import Propuesta

MESES = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"],
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
           "setembro", "outubro", "novembro", "dezembro"],
}

TXT = {
    "es": dict(
        propuesta="Propuesta", para="Para", borrador="Borrador para conversar",
        contaste="Lo que nos contaste", cuesta="Lo que cuesta hoy",
        resuelto="Cómo se ve resuelto", resuelto_h="Un día normal, con esto andando",
        etapas="Cómo trabajaríamos", etapas_h="Por etapas, para aprender antes de invertir más",
        etapa="Etapa", aca="Empezamos aquí", falta="Lo que falta definir",
        falta_h="Tres preguntas para la reunión",
        cta_h="Agendemos 30 minutos",
        cta_p="Este documento es un borrador. En una reunión online lo ajustamos juntos "
              "y definimos alcance y presupuesto.",
        agendar="Agendar la reunión",
    ),
    "pt": dict(
        propuesta="Proposta", para="Para", borrador="Rascunho para conversar",
        contaste="O que você nos contou", cuesta="Quanto isso custa hoje",
        resuelto="Como fica resolvido", resuelto_h="Um dia normal, com isso funcionando",
        etapas="Como trabalharíamos", etapas_h="Por etapas, para aprender antes de investir mais",
        etapa="Etapa", aca="Começamos aqui", falta="O que falta definir",
        falta_h="Três perguntas para a reunião",
        cta_h="Vamos agendar 30 minutos",
        cta_p="Este documento é um rascunho. Em uma reunião online ajustamos juntos "
              "e definimos escopo e orçamento.",
        agendar="Agendar a reunião",
    ),
}


def logo(trazo: str, punto: str, size: int = 30) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{trazo}" '
            f'stroke-width="2" stroke-linecap="round" aria-label="guria.lat">'
            f'<path d="M2 6 H9 C13 6 13 12 17 12"/><path d="M2 12 H17"/>'
            f'<path d="M2 18 H9 C13 18 13 12 17 12"/>'
            f'<circle cx="18.5" cy="12" r="2.2" fill="{punto}" stroke="none"/></svg>')


CSS = """
@page { size: 1280px 720px; margin: 0; }
:root {
  --ink:#111417; --ink-soft:#35383B; --paper:#EFEEE9; --sunk:#E4E2DA; --card:#FFFFFF;
  --rule:#C9C7BE; --rule-dark:#33373B; --muted:#63635B; --muted-dark:#8A8A80; --body-dark:#C3C3BA;
  --signal:#E2502B; --signal-text:#B03A1B; --signal-rule:#B8401E; --on-signal:#17100C;
  --display:"Archivo","Helvetica Neue",Arial,sans-serif;
  --body:"Newsreader",Georgia,"Times New Roman",serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #777; font-family: var(--body); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.slide { width: 1280px; height: 720px; padding: 64px 72px 0; display: flex; flex-direction: column;
  background: var(--paper); color: var(--ink); overflow: hidden; break-after: page; position: relative; }
@media screen { body { padding: 24px; display: flex; flex-direction: column; align-items: center; gap: 24px; } }
.dark { background: var(--ink); color: var(--paper); }
.signal { background: var(--signal); color: var(--on-signal); }
.kicker { font-family: var(--mono); font-size: 13px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }
.kicker b { color: var(--signal-text); font-weight: 500; }
.dark .kicker { color: var(--muted-dark); } .dark .kicker b { color: var(--signal); }
h1, h2, h3 { font-family: var(--display); text-wrap: balance; }
h1 { font-size: 84px; font-weight: 800; line-height: .98; letter-spacing: -.045em; }
h2 { font-size: 54px; font-weight: 800; line-height: 1.04; letter-spacing: -.035em; }
h3 { font-size: 28px; font-weight: 600; line-height: 1.15; letter-spacing: -.02em; }
.body { flex: 1; display: flex; flex-direction: column; justify-content: safe center; gap: 32px; padding-block: 24px; min-height: 0; }
.portada .body { justify-content: space-between; }
.foot { height: 56px; display: flex; align-items: center; justify-content: space-between;
  font-family: var(--mono); font-size: 12px; letter-spacing: .08em; color: var(--muted);
  border-top: 1px solid var(--rule); }
.dark .foot { color: var(--muted-dark); border-color: var(--rule-dark); }
.signal .foot { color: var(--on-signal); border-color: var(--signal-rule); }
.brand { display: flex; align-items: center; gap: 12px; font-family: var(--display); font-weight: 800;
  font-size: 26px; letter-spacing: -.03em; }
.brand b { font-weight: 800; }
.brand span { color: var(--signal); }
.lead { font-size: 34px; line-height: 1.32; font-weight: 300; max-width: 30ch; }
.quote { font-size: 38px; line-height: 1.36; font-weight: 300; max-width: 44ch; }
.cuesta { display: flex; flex-direction: column; gap: 8px; padding-left: 20px; border-left: 3px solid var(--signal); }
.cuesta p { font-family: var(--display); font-weight: 600; font-size: 30px; letter-spacing: -.02em; max-width: 52ch; }
.grid { display: grid; gap: 1px; background: var(--rule); border: 1px solid var(--rule); }
.grid > div { background: var(--paper); padding: 28px 30px; display: flex; flex-direction: column; gap: 10px; }
.n { font-family: var(--mono); font-size: 13px; color: var(--signal-text); letter-spacing: .1em; }
.item { font-size: 25px; line-height: 1.4; font-weight: 400; }
.cols2 { grid-template-columns: 1fr 1fr; }
.cols3 { grid-template-columns: repeat(3, 1fr); }
.etapa h3 { min-height: 2.3em; }
.tres h2 { font-size: 42px; }
.tres .grid > div { padding: 22px 22px; gap: 8px; }
.tres .etapa h3 { font-size: 22px; }
.tres .etapa .obj { font-size: 17px; }
.tres .etapa li { font-size: 13px; }
.etapa .obj { font-size: 20px; line-height: 1.4; color: var(--ink-soft); }
.etapa ul { list-style: none; display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--rule); padding-top: 12px; }
.etapa li { font-family: var(--mono); font-size: 14.5px; line-height: 1.45; color: var(--ink-soft); }
.etapa li::before { content: "· "; color: var(--signal-text); }
.aca { font-family: var(--mono); font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
  color: var(--signal-text); }
.preguntas { display: flex; flex-direction: column; border-top: 1px solid var(--rule); }
.preguntas li { list-style: none; display: grid; grid-template-columns: 72px 1fr; padding: 28px 0;
  border-bottom: 1px solid var(--rule); align-items: baseline; }
.preguntas li span { font-family: var(--mono); font-size: 14px; color: var(--signal-text); }
.preguntas li p { font-family: var(--display); font-weight: 600; font-size: 32px; letter-spacing: -.02em; line-height: 1.2; }
.cta h2 { font-size: 72px; color: var(--on-signal); }
.cta .quote { color: var(--on-signal); max-width: 40ch; }
.boton { align-self: flex-start; background: var(--ink); color: var(--paper); font-family: var(--mono);
  font-size: 16px; letter-spacing: .06em; padding: 18px 26px; text-decoration: none; display: flex; flex-direction: column; gap: 6px; }
.boton small { font-size: 12px; color: var(--muted-dark); letter-spacing: .04em; }
"""


def _slide(clase: str, kicker: str, cuerpo: str, pie: str) -> str:
    return (f'<section class="slide {clase}"><p class="kicker">{kicker}</p>'
            f'<div class="body">{cuerpo}</div><div class="foot">{pie}</div></section>')


def render(p: Propuesta, agenda_url: str, hoy: date | None = None) -> str:
    t, e = TXT[p.idioma], escape
    hoy = hoy or date.today()
    fecha = f"{hoy.day} de {MESES[p.idioma][hoy.month - 1]} de {hoy.year}"

    secciones: list[tuple[str, str, str]] = []  # (clase, título de sección, cuerpo)
    cuerpo = f'<p class="quote">{e(p.lo_que_nos_contaste)}</p>'
    if p.costo_hoy:
        cuerpo += f'<div class="cuesta"><p class="kicker">{t["cuesta"]}</p><p>{e(p.costo_hoy)}</p></div>'
    secciones.append(("", t["contaste"], cuerpo))

    items = "".join(f'<div><span class="n">{i:02d}</span><p class="item">{e(x)}</p></div>'
                    for i, x in enumerate(p.como_se_ve_resuelto[:4], 1))
    secciones.append(("", t["resuelto"], f'<h2>{t["resuelto_h"]}</h2><div class="grid cols2">{items}</div>'))

    etapas = p.etapas[:3]
    cols = "".join(
        f'<div class="etapa"><span class="n">{t["etapa"]} {i}</span>'
        + (f'<span class="aca">{t["aca"]}</span>' if i == 1 else "")
        + f'<h3>{e(x.nombre)}</h3><p class="obj">{e(x.objetivo)}</p>'
        f'<ul>{"".join(f"<li>{e(y)}</li>" for y in x.incluye[:3])}</ul></div>'
        for i, x in enumerate(etapas, 1))
    secciones.append(("tres" if len(etapas) == 3 else "", t["etapas"], f'<h2>{t["etapas_h"]}</h2>'
                                       f'<div class="grid {"cols3" if len(etapas) == 3 else "cols2"}">{cols}</div>'))

    preg = "".join(f'<li><span>{i:02d}</span><p>{e(q)}</p></li>'
                   for i, q in enumerate(p.lo_que_falta_definir[:3], 1))
    secciones.append(("", t["falta"], f'<h2>{t["falta_h"]}</h2><ul class="preguntas">{preg}</ul>'))

    total = len(secciones) + 2
    pie = lambda n: f'<span>guria.lat · {e(p.titulo)}</span><span>{n:02d} / {total:02d}</span>'

    html = [_slide("dark portada", f'<b>{t["propuesta"]}</b> · {fecha}',
                   f'<div class="brand">{logo("#EFEEE9", "#E2502B")}<b>guria<span>.lat</span></b></div>'
                   f'<div style="display:flex;flex-direction:column;gap:24px"><h1>{e(p.titulo)}</h1>'
                   f'<p class="lead" style="color:var(--body-dark)">{t["para"]} {e(p.para)}</p></div>',
                   f'<span>{t["borrador"]}</span><span>01 / {total:02d}</span>')]
    for n, (clase, titulo, cuerpo) in enumerate(secciones, 2):
        html.append(_slide(clase, f"<b>{n - 1:02d}</b> · {titulo}", cuerpo, pie(n)))
    html.append(_slide("signal cta", f'<b style="color:var(--on-signal)">guria.lat</b>',
                       f'<h2>{t["cta_h"]}</h2><p class="quote">{t["cta_p"]}</p>'
                       f'<a class="boton" href="{e(agenda_url)}">{t["agendar"]} →'
                       f'<small>{e(agenda_url)}</small></a>',
                       pie(total)))

    fuentes = ("https://fonts.googleapis.com/css2?family=Archivo:wght@600;800"
               "&family=Newsreader:opsz,wght@6..72,300;6..72,400&family=JetBrains+Mono:wght@400;500&display=swap")
    return (f'<!doctype html><html lang="{"pt-BR" if p.idioma == "pt" else "es"}"><head><meta charset="utf-8">'
            f'<title>{e(p.titulo)} · guria.lat</title><link rel="stylesheet" href="{fuentes}">'
            f'<style>{CSS}</style></head><body>{"".join(html)}</body></html>')


def chromium() -> str | None:
    if os.environ.get("CHROMIUM_BIN"):
        return os.environ["CHROMIUM_BIN"]
    for nombre in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(nombre):
            return shutil.which(nombre)
    # Playwright instalado en el usuario (desarrollo)
    hallados = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")))
    return hallados[-1] if hallados else None


def a_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Imprime el HTML a PDF con Chromium headless. False si no hay Chromium."""
    binario = chromium()
    if not binario:
        return False
    subprocess.run(
        [binario, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
         "--virtual-time-budget=15000",  # tiempo para que carguen las fuentes
         f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
        check=True, capture_output=True, timeout=90,
    )
    return pdf_path.exists()
