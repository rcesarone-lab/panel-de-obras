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

HERE = Path(__file__).parent
JOBS_PATH = HERE / "jobs.json"
DIST_DIR = HERE.parent / "dist"

JOB_CARD_TMPL = """
<div class="job-card" data-job-id="{job_id}">
  <div class="job-main">
    <p class="job-title">{title}</p>
    <p class="job-sub">{platform}</p>
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
  .job-actions{{display:flex;align-items:center;gap:14px;}}
  .btn{{font-family:'IBM Plex Mono',monospace;font-size:12px;text-decoration:none;padding:8px 12px;background:#E8A427;color:#20211D;font-weight:600;}}
  .applied-toggle{{font-family:'IBM Plex Mono',monospace;font-size:12px;display:flex;gap:6px;align-items:center;}}
  footer{{font-family:'IBM Plex Mono',monospace;font-size:11px;opacity:0.6;margin-top:30px;}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Panel de obra</h1>
  <p style="font-family:'IBM Plex Mono',monospace;font-size:13px;">Actualizado automáticamente el {fecha}</p>
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
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def build():
    jobs = json.loads(JOBS_PATH.read_text(encoding="utf-8")) if JOBS_PATH.exists() else []
    cards = "\n".join(
        JOB_CARD_TMPL.format(
            job_id=stable_job_id(j["url"]),
            title=j["title"],
            platform=j["platform"],
            url=j["url"],
        )
        for j in jobs
    )
    html = PAGE_TMPL.format(fecha=datetime.now().strftime("%d-%m-%Y %H:%M"), cards=cards)
    DIST_DIR.mkdir(exist_ok=True)
    (DIST_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"Sitio generado con {len(jobs)} avisos en {DIST_DIR / 'index.html'}")


if __name__ == "__main__":
    build()
