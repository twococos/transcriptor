"""Descàrrega HTTP de les pàgines d'acords: capçaleres de navegador, una petició per segon i domini.

Les capçaleres són les de src/lib/importers/fetch.ts del canconer: sense elles alguns llocs
(Cifra Club, darrere d'Akamai) responen 403.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

CAPCALERES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ca,es;q=0.9,en;q=0.8",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
TEMPS_LIMIT_S = 15
MIDA_MAXIMA = 2_000_000
INTERVAL_DOMINI_S = 1.0

_sessio = requests.Session()
_sessio.headers.update(CAPCALERES)
_ultima: dict[str, float] = {}
_bloqueig = threading.Lock()


def _espera_torn(url: str) -> None:
    domini = urlparse(url).hostname or ""
    with _bloqueig:
        ara = time.monotonic()
        espera = _ultima.get(domini, 0) + INTERVAL_DOMINI_S - ara
        _ultima[domini] = ara + max(espera, 0)
    if espera > 0:
        time.sleep(espera)


def _codificacio(tipus: str, cos: bytes) -> str:
    """La de la capçalera, la del <meta charset> o UTF-8 (requests suposa ISO-8859-1 si no n'hi ha)."""
    m = re.search(r"charset=([\w-]+)", tipus) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", cos[:4096], re.I)
    if m:
        nom = m.group(1)
        return nom.decode() if isinstance(nom, bytes) else nom
    return "utf-8"


def obte(url: str, params: dict | None = None) -> str | None:
    """HTML de la pàgina, o None si no respon 200 (no llança mai: una font que falla s'ignora)."""
    for intent in range(2):
        _espera_torn(url)
        try:
            r = _sessio.get(url, params=params, timeout=TEMPS_LIMIT_S, stream=True)
            cos = r.raw.read(MIDA_MAXIMA + 1, decode_content=True)
        except (requests.RequestException, OSError) as e:
            log.info("Font d'acords: %s (%s)", url, e.__class__.__name__)
            continue
        if r.status_code == 200 and len(cos) <= MIDA_MAXIMA:
            return cos.decode(_codificacio(r.headers.get("Content-Type", ""), cos), errors="replace")
        if r.status_code not in (429, 500, 502, 503, 504):
            log.info("Font d'acords: %s respon %s", url, r.status_code)
            return None
        time.sleep(2 * (intent + 1))
    return None
