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

from job_identity import canonical_url

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
# "paginate_param": nombre del query param que cada sitio usa para pasar de
# página (verificado en vivo comparando urls devueltas en pag. 1 vs pag. 2 —
# CompuTrabajo ignora "pagina" y solo responde a "p"). LinkedIn no tiene
# paginación disponible sin login (probado con &start=25: devuelve la misma
# página 1), así que no lleva esta clave y se scrapea una sola vez.
COMPUTRABAJO_LOCATION_SELECTOR = "p.fs16.fc_base.mt5:not(.dFlex)"
COMPUTRABAJO_COMPANY_SELECTOR = "p.dFlex.fs16.fc_base.mt5 a"

SEARCHES = [
    ("LinkedIn", "https://ar.linkedin.com/jobs/jefe-de-obra-empleos", {"mode": "dom", "selector": "div.base-card", "label": "Jefe de Obra"}),
    ("LinkedIn", "https://ar.linkedin.com/jobs/supervisor-de-obras-empleos", {"mode": "dom", "selector": "div.base-card", "label": "Supervisor de Obras"}),
    ("LinkedIn", "https://ar.linkedin.com/jobs/industria-oil-gas-empleos", {"mode": "dom", "selector": "div.base-card", "label": "Industria Oil & Gas"}),
    # La URL vieja (.../buenos-aires/ofertas-de-trabajo-direccion-de-obra.html)
    # da 404 — ZonaJobs cambió su estructura de URLs. Esta es la vigente,
    # verificada navegando el buscador del sitio en vivo.
    ("ZonaJobs", "https://www.zonajobs.com.ar/empleos-busqueda-jefe-de-obra.html", {"mode": "jsonld", "label": "Jefe de Obra", "paginate_param": "page"}),
    # CompuTrabajo no marca la ubicación con ninguna clase que la identifique
    # (usa las mismas utility classes "fs16 fc_base mt5" que el nombre de la
    # empresa) — el <p> de ubicación es el único de esos que no tiene además
    # la clase "dFlex" (esa sí la tiene el de la empresa), así que los
    # distinguimos por eso.
    ("CompuTrabajo", "https://ar.computrabajo.com/trabajo-de-jefe-de-obra", {"mode": "dom", "selector": "article.box_offer", "location_selector": COMPUTRABAJO_LOCATION_SELECTOR, "company_selector": COMPUTRABAJO_COMPANY_SELECTOR, "label": "Jefe de Obra", "paginate_param": "p"}),
    ("Bumeran", "https://www.bumeran.com.ar/empleos-busqueda-jefe-de-obra.html", {"mode": "jsonld", "label": "Jefe de Obra", "paginate_param": "page"}),
    # Minería: el perfil de Yrlex la incluye (ver KEYWORDS) pero ninguna
    # búsqueda de arriba la cubre — todas son variantes de "obra", así que
    # un aviso titulado p.ej. "Supervisor de Mina" nunca aparecía. Agregado
    # y verificado en vivo (Salta/San Juan entre los resultados reales).
    ("LinkedIn", "https://ar.linkedin.com/jobs/mineria-empleos", {"mode": "dom", "selector": "div.base-card", "label": "Minería"}),
    ("LinkedIn", "https://ar.linkedin.com/jobs/supervisor-de-mina-empleos", {"mode": "dom", "selector": "div.base-card", "label": "Supervisor de Mina"}),
    ("ZonaJobs", "https://www.zonajobs.com.ar/empleos-busqueda-mineria.html", {"mode": "jsonld", "label": "Minería", "paginate_param": "page"}),
    ("CompuTrabajo", "https://ar.computrabajo.com/trabajo-de-mineria", {"mode": "dom", "selector": "article.box_offer", "location_selector": COMPUTRABAJO_LOCATION_SELECTOR, "company_selector": COMPUTRABAJO_COMPANY_SELECTOR, "label": "Minería", "paginate_param": "p"}),
    ("Bumeran", "https://www.bumeran.com.ar/empleos-busqueda-mineria.html", {"mode": "jsonld", "label": "Minería", "paginate_param": "page"}),
]

# Tope de páginas por búsqueda — la paginación corta antes si una página no
# trae avisos nuevos (ver scrape()), así que esto es solo un techo de
# seguridad para no quedar dando vueltas en una búsqueda enorme (LinkedIn
# "minería" tiene 2000+, pero ahí no aplica: no hay paginación sin login).
MAX_PAGES = 5


def paginated_url(base_url: str, param: str, page_num: int) -> str:
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{param}={page_num}"

# Palabras clave del CV para marcar afinidad (no descarta nada, solo puntúa)
KEYWORDS = [
    "obra", "construcción", "piping", "oil", "gas", "minería", "vialidad",
    "nuclear", "energía", "hse", "qa/qc", "uocra", "planta", "montaje",
]


def score(text: str) -> int:
    t = text.lower()
    return sum(1 for k in KEYWORDS if k in t)


GENERIC_LOCATION_SELECTOR = "[class*='location'], [class*='ubicacion'], .job-location, span[class*='place']"
# h4/.subtitle es lo que trae el nombre de empresa en las cards de LinkedIn
# (verificado en vivo); CompuTrabajo usa su propio override (ver SEARCHES).
GENERIC_COMPANY_SELECTOR = "h4, .subtitle, [class*='subtitle'], a[class*='company']"


def extract_dom_cards(page, url, selector, location_selector=None, company_selector=None):
    items = []
    for card in page.query_selector_all(selector):
        title_el = card.query_selector("h3, h2, .title, [class*='title']")
        link_el = card.query_selector("a")
        location_el = card.query_selector(location_selector or GENERIC_LOCATION_SELECTOR)
        company_el = card.query_selector(company_selector or GENERIC_COMPANY_SELECTOR)
        title_text = title_el.inner_text() if title_el else card.inner_text()
        title = title_text.split("\n")[0].strip()
        link = link_el.get_attribute("href") if link_el else url
        location = location_el.inner_text().strip() if location_el else None
        company = company_el.inner_text().strip() if company_el else None
        if link and link.startswith("/"):
            base = re.match(r"https?://[^/]+", url).group(0)
            link = base + link
        if title and link:
            items.append((title, link, location, company))
    return items


def extract_navent_card_map(page):
    """ZonaJobs y Bumeran (grupo Navent) no tienen clases CSS estables
    (styled-components con hashes que cambian en cada deploy), pero cada
    card tiene: un ícono con aria-label="Ubicación" seguido del texto de
    ubicación, y (más arriba, sin ícono) un <h3> con el nombre de empresa —
    lo distinguimos de la fecha ("Publicado hace...") y de los <h3> de
    ubicación/modalidad (que sí están precedidos por un ícono con
    aria-label) tomando el primer <h3> "suelto" que quede. Devuelve
    {path_del_aviso: {"location":..., "company":...}}."""
    return page.evaluate(
        """
        () => {
            const map = {};
            document.querySelectorAll('a[href*="/empleos/"]').forEach(a => {
                const href = a.getAttribute('href');
                if (!map[href]) map[href] = {location: null, company: null};

                const icon = a.querySelector('i[aria-label="Ubicación"]');
                if (icon) {
                    const sibling = icon.nextElementSibling;
                    if (sibling) map[href].location = sibling.textContent.trim();
                }

                const h3s = Array.from(a.querySelectorAll('h3'));
                for (const h3 of h3s) {
                    const text = h3.textContent.trim();
                    if (!text || /^Publicado|^Actualizado/.test(text)) continue;
                    const parentSpan = h3.closest('span');
                    const prev = parentSpan && parentSpan.previousElementSibling;
                    const prevIcon = prev && prev.tagName === 'I' && prev.hasAttribute('aria-label');
                    if (prevIcon) continue;
                    map[href].company = text;
                    break;
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
    traiga avisos reales. El ItemList en sí solo trae name + url, así que
    ubicación y empresa se cruzan aparte con extract_navent_card_map por el
    path de la url (matcheando contra el href relativo de cada card)."""
    card_map = extract_navent_card_map(page)
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
            details = card_map.get(path, {})
            items.append((el["name"], el["url"], details.get("location"), details.get("company")))
        if items:
            return items
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
            paginate_param = cfg.get("paginate_param")
            max_pages = MAX_PAGES if paginate_param else 1
            search_seen_urls = set()  # canónicas, para saber si una página trajo algo nuevo
            found_any_page = False

            for page_num in range(1, max_pages + 1):
                page_url = paginated_url(url, paginate_param, page_num) if page_num > 1 else url
                try:
                    page.goto(page_url, timeout=30000, wait_until="networkidle")
                except PlaywrightTimeoutError:
                    # networkidle a veces no se cumple nunca en sitios con
                    # tracking/ads en background (visto en LinkedIn), pero el
                    # listado ya puede estar completo igual — seguimos e
                    # intentamos extraer en vez de descartar la búsqueda entera.
                    print(f"[warn] {platform} ({page_url}) no llegó a networkidle en el timeout, sigo con lo que cargó")
                except Exception as e:
                    print(f"[warn] fallo en {platform} ({page_url}): {e}")
                    break

                page.wait_for_timeout(2000)  # deja asentar el render JS

                try:
                    if cfg["mode"] == "jsonld":
                        items = extract_jsonld_items(page)
                    else:
                        items = extract_dom_cards(
                            page, page_url, cfg["selector"], cfg.get("location_selector"), cfg.get("company_selector")
                        )
                except Exception as e:
                    print(f"[warn] no se pudo extraer {platform} ({page_url}): {e}")
                    break

                if not items:
                    if not found_any_page:
                        print(f"[warn] {platform} ({page_url}) no trajo avisos — revisar selector o bloqueo de bot")
                    break  # página vacía: no hay más que paginar

                new_in_this_page = 0
                for title, link, location, company in items:
                    key = canonical_url(link)
                    if key in search_seen_urls:
                        continue
                    search_seen_urls.add(key)
                    new_in_this_page += 1
                    results.append({
                        "platform": platform,
                        "title": title,
                        "url": link,
                        "location": location,
                        "company": company,
                        "score": score(title),
                        "found_at": datetime.now(timezone.utc).isoformat(),
                    })
                found_any_page = True

                if paginate_param and new_in_this_page == 0:
                    # La página siguiente no trajo nada que no tuviéramos ya
                    # (se acabaron los resultados reales) — cortar en vez de
                    # seguir pidiendo páginas de más.
                    break

        browser.close()

    # dedup por url canónica (sin query/fragment de tracking) — el mismo
    # aviso puede salir en más de una búsqueda guardada con distintos
    # parámetros de tracking y hay que tratarlo como uno solo.
    seen = {}
    for r in results:
        seen[canonical_url(r["url"])] = r
    deduped = sorted(seen.values(), key=lambda r: -r["score"])

    OUT_PATH.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardados {len(deduped)} avisos en {OUT_PATH}")


if __name__ == "__main__":
    scrape()
