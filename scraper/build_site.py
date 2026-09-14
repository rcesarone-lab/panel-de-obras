"""
Toma jobs.json y arma dist/index.html: el mismo panel visual que ya tenías,
pero con los avisos que trajo el scraper esa mañana en vez de la muestra fija.

El "Marcar como postulado" queda guardado en localStorage del navegador de
Yrlex (por dispositivo) — no requiere backend ni login.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from job_identity import canonical_url
from scrape_jobs import SEARCHES

HERE = Path(__file__).parent
JOBS_PATH = HERE / "jobs.json"
DIST_DIR = HERE.parent / "dist"

# Datos fijos del perfil de Yrlex para el header del panel. Hasta que exista
# un buscador dinámico basado en CV (a futuro), quedan hardcodeados acá.
CANDIDATE_NAME = "Yrlex Suterlath Olivares Zambrano"
CANDIDATE_ROLE = "Coordinador / Jefe de Obras / Inspector de Obras"
CANDIDATE_LOCATION = "Quilmes, Buenos Aires"
CANDIDATE_AVAILABILITY = "Nacional — inmediata"
CANDIDATE_TAGS = [
    "Jefe / Coordinador de Obras",
    "Inspector y Supervisor de Obras",
    "Oil & Gas / Piping",
    "Energía Nuclear / Renovables",
    "Minería",
    "Vialidad e Infraestructura",
    "UOCRA / QA-QC / HSE",
]

# Home de cada plataforma, para el link de la cabecera de cada bloque en la
# sección "Búsquedas activas por plataforma".
PLATFORM_HOME_LINKS = {
    "LinkedIn": "https://ar.linkedin.com/jobs",
    "ZonaJobs": "https://www.zonajobs.com.ar",
    "CompuTrabajo": "https://ar.computrabajo.com",
    "Bumeran": "https://www.bumeran.com.ar",
}

CALLOUT_TEXT = (
    "Todos los días a las 06:00 se recorren las búsquedas guardadas de abajo "
    "en LinkedIn, ZonaJobs, CompuTrabajo y Bumeran, filtradas por tus roles "
    "y sectores, y se arma la lista de avisos vigentes que ves más abajo. "
    "Cada aviso te lleva directo a la página original, donde podés "
    "postularte con la “postulación fácil” de cada sitio (1 clic, con tu CV "
    "ya cargado). Tildá “Ya me postulé” para llevar el registro — queda "
    "guardado en este navegador."
)

HEADER_TMPL = """
<header class="plate">
  <div class="plate-top">
    <div class="plate-title">
      <h1>PANEL DE BÚSQUEDA — OBRAS</h1>
      <p>{name} · {role}</p>
    </div>
    <div class="plate-meta">
      <div>UBICACIÓN <span>{location}</span></div>
      <div>DISPONIBILIDAD <span>{availability}</span></div>
      <div>ACTUALIZADO <span>{fecha}</span></div>
    </div>
  </div>
  <div class="tag-row">
    {tags}
  </div>
</header>
"""

TAG_TMPL = '<span class="tag">{tag}</span>'

PLATFORM_LINK_TMPL = (
    '<a href="{url}" target="_blank" rel="noopener">'
    '<span class="role">{label}</span><span class="go">ver avisos →</span></a>'
)

PLATFORM_BLOCK_TMPL = """
<div class="platform">
  <div class="platform-head">
    <h3>{platform}</h3>
    <a class="home-link" href="{home}" target="_blank" rel="noopener">{home_label}</a>
  </div>
  <div class="links-grid">
    {links}
  </div>
</div>
"""

JOB_CARD_TMPL = """
<div class="job-card" data-job-id="{job_id}">
  <div class="job-main">
    <p class="job-title">{title}</p>
    <p class="job-sub">{platform}</p>
    <p class="job-location">📍 {location}</p>
  </div>
  <div class="job-actions">
    <label class="applied-toggle">
      <input type="checkbox" class="applied-checkbox" data-job-id="{job_id}">
      Ya me postulé
    </label>
    <a class="btn primary" href="{url}" target="_blank" rel="noopener">Ver y postular</a>
  </div>
</div>
"""

PAGE_TMPL = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Panel de obra — actualizado {fecha}</title>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
  body{{font-family:'IBM Plex Sans',sans-serif;background:#EDEAE1;color:#20211D;margin:0;}}
  .wrap{{max-width:1000px;margin:0 auto;padding:28px 20px 80px;}}
  h1{{font-family:'Oswald',sans-serif;}}
  .job-card{{border:1px solid #B7B2A2;background:#F6F4EC;padding:14px 18px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;}}
  .job-card.applied{{opacity:0.5;}}
  .job-title{{font-family:'Oswald',sans-serif;font-weight:600;margin:0 0 4px;}}
  .job-sub{{font-family:'IBM Plex Mono',monospace;font-size:12px;color:#3C5A6E;margin:0;}}
  .job-location{{font-family:'IBM Plex Mono',monospace;font-size:12px;color:#B5502D;margin:4px 0 0;}}
  .job-actions{{display:flex;align-items:center;gap:14px;}}
  .btn{{font-family:'IBM Plex Mono',monospace;font-size:12px;text-decoration:none;padding:8px 12px;background:#E8A427;color:#20211D;font-weight:600;}}
  .applied-toggle{{font-family:'IBM Plex Mono',monospace;font-size:12px;display:flex;gap:6px;align-items:center;}}
  footer{{font-family:'IBM Plex Mono',monospace;font-size:11px;opacity:0.6;margin-top:30px;}}
  header.plate{{border:2px solid #20211D;background:#F6F4EC;padding:22px 24px;position:relative;margin-bottom:28px;}}
  header.plate::before{{content:"";position:absolute;top:8px;left:8px;right:8px;bottom:8px;border:1px solid #B7B2A2;pointer-events:none;}}
  .plate-top{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;}}
  .plate-title h1{{font-family:'Oswald',sans-serif;font-weight:700;font-size:clamp(28px,4.2vw,42px);letter-spacing:0.5px;margin:0 0 4px;line-height:1.05;}}
  .plate-title p{{margin:0;color:#3C5A6E;font-family:'IBM Plex Mono',monospace;font-size:13px;}}
  .plate-meta{{font-family:'IBM Plex Mono',monospace;font-size:12px;text-align:right;color:#20211D;opacity:0.75;line-height:1.7;}}
  .plate-meta div span{{color:#B5502D;}}
  .tag-row{{margin-top:16px;display:flex;flex-wrap:wrap;gap:8px;}}
  .tag{{border:1px solid #3C5A6E;color:#2A4152;font-family:'IBM Plex Mono',monospace;font-size:11.5px;padding:4px 9px;background:transparent;}}
  h2.section-title{{font-family:'Oswald',sans-serif;font-size:22px;font-weight:600;margin:44px 0 6px;padding-bottom:8px;border-bottom:2px solid #20211D;display:flex;align-items:baseline;gap:10px;}}
  h2.section-title .num{{font-family:'IBM Plex Mono',monospace;font-size:14px;color:#B5502D;}}
  p.section-note{{margin:6px 0 20px;font-size:14.5px;color:#20211D;opacity:0.8;max-width:70ch;}}
  .platform{{border:1px solid #B7B2A2;background:#F6F4EC;margin-bottom:16px;}}
  .platform-head{{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:#E2DECF;border-bottom:1px solid #B7B2A2;}}
  .platform-head h3{{font-family:'Oswald',sans-serif;font-size:17px;margin:0;font-weight:600;}}
  .platform-head a.home-link{{font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:#3C5A6E;text-decoration:none;border-bottom:1px dotted #3C5A6E;}}
  .links-grid{{display:grid;grid-template-columns:repeat(auto-fill, minmax(230px, 1fr));gap:1px;background:#B7B2A2;}}
  .links-grid a{{display:block;background:#F6F4EC;padding:12px 14px;text-decoration:none;color:#20211D;font-size:14px;}}
  .links-grid a:hover{{background:#E2DECF;}}
  .links-grid a .role{{display:block;font-weight:500;}}
  .links-grid a .go{{font-family:'IBM Plex Mono',monospace;font-size:11px;color:#B5502D;}}
  .callout{{border-left:3px solid #B5502D;background:#F6F4EC;padding:14px 18px;font-size:14px;margin:20px 0;}}
  .callout strong{{color:#B5502D;}}
</style>
</head>
<body>
<div class="wrap">
  {header}
  <div class="callout"><strong>Cómo funciona este panel.</strong> {callout_text}</div>
  <h2 class="section-title"><span class="num">01</span> Búsquedas activas por plataforma</h2>
  <p class="section-note">Filtradas según los roles y sectores de tu perfil. Guardalas como alerta en cada sitio para recibir avisos nuevos por mail automáticamente.</p>
  {platform_links}
  <h2 class="section-title"><span class="num">02</span> Avisos encontrados hoy ({job_count})</h2>
  <p class="section-note">Se actualiza solo, todos los días a las 06:00.</p>
  {cards}
  <footer>Generado por el scraper diario. Lo tildado como "ya me postulé" se guarda solo en este navegador.</footer>
</div>
<script>
  document.querySelectorAll('.applied-checkbox').forEach(cb => {{
    const id = cb.dataset.jobId;
    try {{
      cb.checked = localStorage.getItem('applied:' + id) === '1';
      cb.closest('.job-card').classList.toggle('applied', cb.checked);
    }} catch (e) {{}}
    cb.addEventListener('change', () => {{
      try {{
        localStorage.setItem('applied:' + id, cb.checked ? '1' : '0');
        cb.closest('.job-card').classList.toggle('applied', cb.checked);
      }} catch (e) {{}}
    }});
  }});
</script>
</body>
</html>
"""


def stable_job_id(url: str) -> str:
    # hash() nativo de Python está aleatorizado por proceso (PEP 456) — el
    # mismo aviso tendría un id distinto en cada corrida del workflow,
    # rompiendo el "Ya me postulé" guardado en localStorage al día siguiente.
    # canonical_url() además saca los tokens de tracking (LinkedIn/
    # CompuTrabajo) que cambian entre corridas aunque sea el mismo aviso.
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def build_header_html(fecha: str) -> str:
    tags_html = "\n    ".join(TAG_TMPL.format(tag=t) for t in CANDIDATE_TAGS)
    return HEADER_TMPL.format(
        name=CANDIDATE_NAME,
        role=CANDIDATE_ROLE,
        location=CANDIDATE_LOCATION,
        availability=CANDIDATE_AVAILABILITY,
        fecha=fecha,
        tags=tags_html,
    )


def build_platform_links_html() -> str:
    # Se arma a partir de SEARCHES (la fuente real de lo que el scraper
    # busca) para que esta sección nunca quede desincronizada de las
    # búsquedas que realmente corren todos los días.
    grouped = {}
    for platform, url, cfg in SEARCHES:
        grouped.setdefault(platform, []).append((cfg.get("label", platform), url))

    blocks = []
    for platform, entries in grouped.items():
        links_html = "\n    ".join(
            PLATFORM_LINK_TMPL.format(url=url, label=label) for label, url in entries
        )
        home = PLATFORM_HOME_LINKS.get(platform, "#")
        home_label = home.split("//", 1)[-1]
        blocks.append(
            PLATFORM_BLOCK_TMPL.format(
                platform=platform, home=home, home_label=home_label, links=links_html
            )
        )
    return "\n".join(blocks)


def build():
    jobs = json.loads(JOBS_PATH.read_text(encoding="utf-8")) if JOBS_PATH.exists() else []
    cards = "\n".join(
        JOB_CARD_TMPL.format(
            job_id=stable_job_id(j["url"]),
            title=j["title"],
            platform=j["platform"],
            location=j.get("location") or "No especificado",
            url=j["url"],
        )
        for j in jobs
    )
    fecha = datetime.now().strftime("%d-%m-%Y %H:%M")
    html = PAGE_TMPL.format(
        fecha=fecha,
        header=build_header_html(fecha),
        callout_text=CALLOUT_TEXT,
        platform_links=build_platform_links_html(),
        job_count=len(jobs),
        cards=cards,
    )
    DIST_DIR.mkdir(exist_ok=True)
    (DIST_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"Sitio generado con {len(jobs)} avisos en {DIST_DIR / 'index.html'}")


if __name__ == "__main__":
    build()
