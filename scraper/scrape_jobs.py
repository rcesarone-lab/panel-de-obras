"""
Scraper diario de avisos de obra para Yrlex Suterlath.

Visita las búsquedas guardadas de cada plataforma (definidas en SEARCHES),
espera a que el JS renderice el listado, y extrae título / empresa /
ubicación / link de cada aviso a jobs.json.

IMPORTANTE: este script no fue probado contra los sitios en vivo (el entorno
donde se escribió no tiene acceso a internet). Los selectores CSS de abajo
son un punto de partida razonable según la estructura típica de cada sitio,
pero hay que correrlo, mirar qué trae, y ajustar los selectores que fallen.
Esa iteración es justamente para lo que conviene usar Claude Code: corre el
script, te muestra el resultado, y vos (o Claude Code) ajustan lo que no
matchee.

Requiere: pip install playwright && playwright install chromium
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_PATH = Path(__file__).parent / "jobs.json"

# Cada entrada: (plataforma, url de búsqueda ya filtrada, selector CSS del
# contenedor de cada aviso individual dentro del listado)
SEARCHES = [
    ("LinkedIn", "https://ar.linkedin.com/jobs/jefe-de-obra-empleos", "div.base-card"),
    ("LinkedIn", "https://ar.linkedin.com/jobs/supervisor-de-obras-empleos", "div.base-card"),
    ("LinkedIn", "https://ar.linkedin.com/jobs/industria-oil-gas-empleos", "div.base-card"),
    ("ZonaJobs", "https://www.zonajobs.com.ar/buenos-aires/ofertas-de-trabajo-direccion-de-obra.html", "div[id^='JT_']"),
    ("CompuTrabajo", "https://ar.computrabajo.com/trabajo-de-jefe-de-obra", "article.box_offer"),
    ("Bumeran", "https://www.bumeran.com.ar/empleos-busqueda-jefe-de-obra.html", "a[data-testid='listing-card']"),
]

# Palabras clave del CV para marcar afinidad (no descarta nada, solo puntúa)
KEYWORDS = [
    "obra", "construcción", "piping", "oil", "gas", "minería", "vialidad",
    "nuclear", "energía", "hse", "qa/qc", "uocra", "planta", "montaje",
]


def score(text: str) -> int:
    t = text.lower()
    return sum(1 for k in KEYWORDS if k in t)


def scrape():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="es-AR")

        for platform, url, selector in SEARCHES:
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                page.wait_for_timeout(2000)  # deja asentar el render JS
                cards = page.query_selector_all(selector)
                for card in cards[:15]:
                    title_el = card.query_selector("h3, h2, .title, [class*='title']")
                    link_el = card.query_selector("a")
                    title = title_el.inner_text().strip() if title_el else card.inner_text().split("\n")[0].strip()
                    link = link_el.get_attribute("href") if link_el else url
                    if link and link.startswith("/"):
                        base = re.match(r"https?://[^/]+", url).group(0)
                        link = base + link
                    if not title or not link:
                        continue
                    results.append({
                        "platform": platform,
                        "title": title,
                        "url": link,
                        "score": score(title),
                        "found_at": datetime.now(timezone.utc).isoformat(),
                    })
            except Exception as e:
                print(f"[warn] fallo en {platform} ({url}): {e}")

        browser.close()

    # dedup por url
    seen = {}
    for r in results:
        seen[r["url"]] = r
    deduped = sorted(seen.values(), key=lambda r: -r["score"])

    OUT_PATH.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardados {len(deduped)} avisos en {OUT_PATH}")


if __name__ == "__main__":
    scrape()
