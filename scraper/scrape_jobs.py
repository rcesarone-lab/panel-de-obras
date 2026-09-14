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
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

OUT_PATH = Path(__file__).parent / "jobs.json"

# User-agent real de escritorio: ZonaJobs, Bumeran y CompuTrabajo están detrás
# de Cloudflare / bot-detection y devuelven un challenge o 403 al user-agent
# por defecto de Playwright. Confirmado inspeccionando el HTML/screenshot
# post-render de cada uno antes de tocar esto (ver notas en los selectores
# de abajo) — no es una optimización, es lo que destraba el acceso.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Cada entrada: (plataforma, url de búsqueda ya filtrada, cómo extraer cada
# aviso del listado)
#
# - modo "dom": selector CSS del contenedor de cada aviso; título/link se
#   buscan dentro con heurísticas genéricas.
# - modo "jsonld": el sitio no tiene clases CSS estables (styled-components
#   con hashes que cambian en cada deploy de ZonaJobs/Bumeran), pero publica
#   un <script type="application/ld+json"> con @type "ItemList" que ya trae
#   título + url de cada aviso — mucho más confiable que perseguir clases.
SEARCHES = [
    ("LinkedIn", "https://ar.linkedin.com/jobs/jefe-de-obra-empleos", {"mode": "dom", "selector": "div.base-card"}),
    ("LinkedIn", "https://ar.linkedin.com/jobs/supervisor-de-obras-empleos", {"mode": "dom", "selector": "div.base-card"}),
    ("LinkedIn", "https://ar.linkedin.com/jobs/industria-oil-gas-empleos", {"mode": "dom", "selector": "div.base-card"}),
    # La URL vieja (.../buenos-aires/ofertas-de-trabajo-direccion-de-obra.html)
    # da 404 — ZonaJobs cambió su estructura de URLs. Esta es la vigente,
    # verificada navegando el buscador del sitio en vivo.
    ("ZonaJobs", "https://www.zonajobs.com.ar/empleos-busqueda-jefe-de-obra.html", {"mode": "jsonld"}),
    # CompuTrabajo no marca la ubicación con ninguna clase que la identifique
    # (usa las mismas utility classes "fs16 fc_base mt5" que el nombre de la
    # empresa) — el <p> de ubicación es el único de esos que no tiene además
    # la clase "dFlex", así que lo distinguimos por eso.
    ("CompuTrabajo", "https://ar.computrabajo.com/trabajo-de-jefe-de-obra", {"mode": "dom", "selector": "article.box_offer", "location_selector": "p.fs16.fc_base.mt5:not(.dFlex)"}),
    ("Bumeran", "https://www.bumeran.com.ar/empleos-busqueda-jefe-de-obra.html", {"mode": "jsonld"}),
]

# Palabras clave del CV para marcar afinidad (no descarta nada, solo puntúa)
KEYWORDS = [
    "obra", "construcción", "piping", "oil", "gas", "minería", "vialidad",
    "nuclear", "energía", "hse", "qa/qc", "uocra", "planta", "montaje",
]


def score(text: str) -> int:
    t = text.lower()
    return sum(1 for k in KEYWORDS if k in t)


GENERIC_LOCATION_SELECTOR = "[class*='location'], [class*='ubicacion'], .job-location, span[class*='place']"


def extract_dom_cards(page, url, selector, location_selector=None):
    items = []
    for card in page.query_selector_all(selector)[:15]:
        title_el = card.query_selector("h3, h2, .title, [class*='title']")
        link_el = card.query_selector("a")
        location_el = card.query_selector(location_selector or GENERIC_LOCATION_SELECTOR)
        title_text = title_el.inner_text() if title_el else card.inner_text()
        title = title_text.split("\n")[0].strip()
        link = link_el.get_attribute("href") if link_el else url
        location = location_el.inner_text().strip() if location_el else None
        if link and link.startswith("/"):
            base = re.match(r"https?://[^/]+", url).group(0)
            link = base + link
        if title and link:
            items.append((title, link, location))
    return items


def extract_navent_location_map(page):
    """ZonaJobs y Bumeran (grupo Navent) no tienen clases CSS estables, pero
    cada card marca la ubicación con un ícono con aria-label="Ubicación"
    (atributo semántico, no un hash de styled-components) seguido del texto
    en el elemento hermano. Devuelve {path_del_aviso: texto_ubicacion}."""
    return page.evaluate(
        """
        () => {
            const map = {};
            document.querySelectorAll('i[aria-label="Ubicación"]').forEach(icon => {
                const sibling = icon.nextElementSibling;
                const text = sibling ? sibling.textContent.trim() : null;
                const a = icon.closest('a[href*="/empleos/"]');
                if (a && text) {
                    map[a.getAttribute('href')] = text;
                }
            });
            return map;
        }
        """
    )


def extract_jsonld_items(page):
    """Lee los <script type="application/ld+json"> con @type ItemList.
    Puede haber varios bloques ld+json en la página (breadcrumbs, etc.) y
    alguno vacío antes de la hidratación; nos quedamos con el primero que
    traiga avisos reales. El ItemList en sí solo trae name + url, así que la
    ubicación se cruza aparte con extract_navent_location_map por el path
    de la url (matcheando contra el href relativo del ícono de ubicación)."""
    location_map = extract_navent_location_map(page)
    for script in page.query_selector_all('script[type="application/ld+json"]'):
        raw = script.inner_text()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "ItemList":
            continue
        elements = data.get("itemListElement") or []
        items = []
        for el in elements:
            if not (el.get("name") and el.get("url")):
                continue
            path = urlparse(el["url"]).path
            location = location_map.get(path)
            items.append((el["name"], el["url"], location))
        if items:
            return items[:15]
    return []


def scrape():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="es-AR",
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "es-AR,es;q=0.9,en;q=0.8"},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        for platform, url, cfg in SEARCHES:
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
            except PlaywrightTimeoutError:
                # networkidle a veces no se cumple nunca en sitios con
                # tracking/ads en background (visto en LinkedIn), pero el
                # listado ya puede estar completo igual — seguimos e
                # intentamos extraer en vez de descartar la búsqueda entera.
                print(f"[warn] {platform} ({url}) no llegó a networkidle en el timeout, sigo con lo que cargó")
            except Exception as e:
                print(f"[warn] fallo en {platform} ({url}): {e}")
                continue

            page.wait_for_timeout(2000)  # deja asentar el render JS

            try:
                if cfg["mode"] == "jsonld":
                    items = extract_jsonld_items(page)
                else:
                    items = extract_dom_cards(page, url, cfg["selector"], cfg.get("location_selector"))
            except Exception as e:
                print(f"[warn] no se pudo extraer {platform} ({url}): {e}")
                continue

            if not items:
                print(f"[warn] {platform} ({url}) no trajo avisos — revisar selector o bloqueo de bot")

            for title, link, location in items:
                results.append({
                    "platform": platform,
                    "title": title,
                    "url": link,
                    "location": location,
                    "score": score(title),
                    "found_at": datetime.now(timezone.utc).isoformat(),
                })

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
