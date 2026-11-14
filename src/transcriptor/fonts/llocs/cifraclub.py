"""Cifra Club (www.cifraclub.com.br, i en castellà www.cifraclub.com): molt repertori brasiler i
internacional, i també català (Txarango, Sau…). Una versió principal per cançó.

- Cerca: l'API del cercador de la web (solr.sscdn.co/cc/c7/?q=…), que respon JSON sense
  protecció: `response.docs` amb `tipo` "2" per a les cançons, `art`, `txt` (títol), `dns`
  (slug de l'artista) i `url` (slug de la cançó). La tab és a
  https://www.cifraclub.com.br/{dns}/{url}/.
- Les pàgines són darrere d'Akamai, que respon 403 a `http.obte` i a un navegador que es presenta
  com a "HeadlessChrome": es baixen amb el navegador sense finestra (navegador.py).
- Tab: el `<pre data-chord-content>` (abans, el `<pre>` de `.cifra_cnt`), amb cada acord en un
  `<b>` a la línia de sobre de la lletra i les seccions com a "[Refrão]" (o "[Intro] A  D", secció
  i acords junts) a l'inici de línia. Els dedilhados porten fletxes de rasgueig i "Parte 1 de 3",
  que es treuen. Títol a `h1`, artista al `<title>` ("Cançó - Artista - Cifra Club"), to i capo al
  text "Tom: F#m (com forma de Em)" i "Capotraste: 2ª casa".
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .. import http
from ..model import Candidat, TabCrua
from ..navegador import Navegador
from ..text_pla import a_content
from . import acceptable, pla, puntuacio
from .lacuerda import linies_pre, separa_seccio

log = logging.getLogger(__name__)

LLOC = "cifraclub"
ARREL = "https://www.cifraclub.com.br"
URL_CERCA = "https://solr.sscdn.co/cc/c7/"
EXPRESSIO_HTML = ("document.querySelector('pre[data-chord-content], .cifra_cnt pre')"
                  " && document.documentElement.outerHTML")
_RE_SOBRA = re.compile(r"\s*(?:[↓↑]+\s*)+|\s*Parte \d+ de \d+.*", re.I)  # fletxes i "Parte 2 de 3 - 2x"


def _text(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def candidats(resposta: str, titol: str, artista: str) -> list[Candidat]:
    """Les cançons de la resposta del cercador que quadren, la millor primer (com a molt una)."""
    try:
        docs = json.loads(resposta)["response"]["docs"]
    except (ValueError, KeyError, TypeError):
        return []
    cs = [Candidat(lloc=LLOC, url=f"{ARREL}/{d['dns']}/{d['url']}/", titol=d.get("txt") or "", artista=d.get("art") or "")
          for d in docs if str(d.get("tipo")) == "2" and d.get("dns") and d.get("url")]
    cs = [c for c in cs if acceptable(titol, artista, c.titol, c.artista)]
    cs.sort(key=lambda c: -puntuacio(titol, artista, c.titol, c.artista))
    return cs[:1]


def cerca(titol: str, artista: str, idioma: str | None = None, nav: Navegador | None = None) -> list[Candidat]:
    try:
        # Sense accents: "mediterrània" no troba res i "mediterrania" sí
        for q in dict.fromkeys(q for q in (pla(f"{titol} {artista}"), pla(titol)) if q):
            resposta = http.obte(URL_CERCA, {"q": q, "limit": "10"})
            cs = candidats(resposta, titol, artista) if resposta else []
            if cs:
                return cs
        return []
    except Exception:  # noqa: BLE001
        log.info("Cifra Club: la cerca ha fallat", exc_info=True)
        return []


def _artista_de_titol(titol_pagina: str) -> str:
    """"Wonderwall - Oasis - Cifra Club" → "Oasis"."""
    parts = [p.strip() for p in titol_pagina.split(" - ")]
    return parts[-2] if len(parts) >= 3 and re.search(r"cifra ?club", parts[-1], re.I) else ""


def _artista_de_url(url: str) -> str:
    seg = [s for s in urlparse(url).path.split("/") if s]
    return " ".join(w.capitalize() for w in seg[0].split("-")) if seg else ""


def parseja(html: str, url: str) -> TabCrua | None:
    try:
        sopa = BeautifulSoup(html, "html.parser")
        pre = sopa.select_one("pre[data-chord-content]") or sopa.select_one(".cifra_cnt pre") or sopa.select_one("pre")
        if pre is None:
            return None
        titol = _text(sopa.select_one("h1.t1")) or _text(sopa.select_one("h1"))
        artista = (_artista_de_titol(_text(sopa.select_one("title"))) or _text(sopa.select_one("h2.t3"))
                   or _artista_de_url(url))
        linies = []
        for text, acords in linies_pre(pre, "b"):
            if not acords and _RE_SOBRA.fullmatch(text):
                continue
            linies += separa_seccio(text, acords)
        content = a_content(linies)
        if not content:
            return None
        tot = _text(sopa.body or sopa)
        m = re.search(r"(\d+)", _text(sopa.select_one("#cifra_capo"))) or re.search(r"Capotraste\s*:?\s*(?:na\s+)?(\d+)", tot, re.I)
        capo = int(m.group(1)) if m and int(m.group(1)) <= 12 else 0
        m = re.search(r"\bTom\s*:\s*([A-G][#b]?m?)(?![\w#])", tot)
        to = _text(sopa.select_one("#cifra_tom a")).replace(" ", "") or (m.group(1) if m else None)
        return TabCrua(lloc=LLOC, url=url, titol=titol, artista=artista, content=content, capo=capo, to=to)
    except Exception:  # noqa: BLE001
        log.info("Cifra Club: no s'ha pogut llegir %s", url, exc_info=True)
        return None


def baixa(c: Candidat, nav: Navegador | None = None) -> TabCrua | None:
    try:
        html = c.extra.get("html") or (nav.avalua(c.url, EXPRESSIO_HTML) if nav else http.obte(c.url))
        return parseja(html, c.url) if html else None
    except Exception:  # noqa: BLE001
        log.info("Cifra Club: no s'ha pogut baixar %s", c.url, exc_info=True)
        return None
