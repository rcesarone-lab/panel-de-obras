"""
Identidad estable de un aviso a partir de su URL.

LinkedIn y CompuTrabajo meten tokens de tracking en la URL de cada aviso
(?trackingId=..., #lc=ListOffers-Score4-0) que cambian entre corridas del
scraper aunque sea exactamente el mismo aviso. Si se hashea la URL completa,
el mismo aviso saca un id distinto cada día -> el "Ya me postulé" guardado
en localStorage se pierde, y el mismo aviso puede aparecer duplicado si
salió en más de una búsqueda guardada. canonical_url() se queda solo con
esquema + host + path, así queda estable entre corridas.

Usado tanto por scrape_jobs.py (dedup) como por build_site.py (job-id) —
tienen que usar exactamente la misma normalización para identificar el
mismo aviso.
"""

from urllib.parse import urlparse, urlunparse


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
