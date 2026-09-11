# Panel de obras — actualización diaria

Repo mínimo para que Yrlex tenga un sitio (GitHub Pages) que se actualiza
solo, una vez por día, con avisos nuevos de las búsquedas guardadas.

## Qué hace cada pieza

- `scraper/scrape_jobs.py` — abre cada búsqueda guardada con un navegador
  headless (Playwright, porque Bumeran/ZonaJobs renderizan todo con JS) y
  guarda lo que encuentra en `scraper/jobs.json`.
- `scraper/build_site.py` — convierte ese `jobs.json` en `dist/index.html`,
  con el checkbox "Ya me postulé" (se guarda en el navegador de quien lo
  mira, sin backend).
- `.github/workflows/daily-update.yml` — corre las dos cosas todos los días
  a las 06:00 (hora Argentina) y publica `dist/` en GitHub Pages.

## Puesta en marcha (recomendado: hacerlo desde Claude Code)

1. Creá un repo nuevo en GitHub y subí esta carpeta.
2. En **Settings → Pages**, elegí la rama `gh-pages` como origen (la crea
   sola el workflow la primera vez que corre).
3. En **Settings → Actions → General**, asegurate de que los workflows
   tengan permiso de "Read and write" (para que puedan pushear a
   `gh-pages`).
4. Corré el workflow una vez a mano desde la pestaña **Actions →
   "Actualizar panel de obras" → Run workflow**, para ver que efectivamente
   trae avisos.

## Por qué conviene iterarlo con Claude Code y no en este chat

`scraper/scrape_jobs.py` **no fue probado contra los sitios reales** — el
entorno donde se escribió no tiene acceso a internet. Es muy probable que
algún selector CSS no matchee al primer intento, o que algún sitio bloquee
al bot. Claude Code puede correr el script contra los sitios en vivo, ver
qué trae (o qué falla), ajustar los selectores, y commitear el arreglo —
iteración que en este chat no puedo hacer de punta a punta.
