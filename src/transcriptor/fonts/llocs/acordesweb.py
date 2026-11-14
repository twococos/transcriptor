"""AcordesWeb (acordesweb.com): web espanyola gran, amb força repertori català (Cesk Freixas,
Txarango…). Sense protecció: tot amb `http.obte`.

- Cerca: https://acordesweb.com/buscar.php?buscar=<títol artista>. Cada cançó és un
  `<a class="card" href=".../cancion/{artista}/{cançó}">` amb dos `<div>`: el títol i l'artista.
- Tab: el `<pre id="chordsPre">`, amb cada acord en un `<a>` a la línia de sobre de la lletra i les
  línies separades per `<br>`. Títol a `h1.s-title`, artista al `<title>` ("Cançó - Artista:
  Acordes para Guitarra…").
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .. import http
from ..model import Candidat, TabCrua
from ..text_pla import a_content
from . import acceptable, pla, puntuacio
from .lacuerda import linies_pre, separa_seccio

log = logging.getLogger(__name__)

LLOC = "acordesweb"
URL_CERCA = "https://acordesweb.com/buscar.php"
VERSIONS = 2


def _text(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def resultats_cerca(html: str) -> list[tuple[str, str, str]]:
    """[(url, títol, artista)] de les cançons d'una pàgina de cerca."""
    sopa = BeautifulSoup(html, "html.parser")
    sortida = []
    for a in sopa.select('a.card[href*="/cancion/"]'):
        divs = [_text(d) for d in a.find_all("div", recursive=False)]
        if len(divs) >= 2 and divs[0]:
            sortida.append((a["href"], divs[0], divs[1]))
    return list(dict.fromkeys(sortida))


def cerca(titol: str, artista: str, idioma: str | None = None) -> list[Candidat]:
    try:
        for q in dict.fromkeys(q for q in (pla(f"{titol} {artista}"), pla(titol)) if q):
            html = http.obte(URL_CERCA, {"buscar": q})
            cs = [Candidat(lloc=LLOC, url=u, titol=t, artista=a) for u, t, a in resultats_cerca(html or "")
                  if acceptable(titol, artista, t, a)]
            if cs:
                cs.sort(key=lambda c: -puntuacio(titol, artista, c.titol, c.artista))
                return cs[:VERSIONS]
        return []
    except Exception:  # noqa: BLE001
        log.info("AcordesWeb: la cerca ha fallat", exc_info=True)
        return []


def _artista_de_url(url: str) -> str:
    seg = [s for s in urlparse(url).path.split("/") if s]
    return " ".join(w.capitalize() for w in seg[1].split("-")) if len(seg) >= 3 else ""


def parseja(html: str, url: str) -> TabCrua | None:
    try:
        sopa = BeautifulSoup(html, "html.parser")
        pre = sopa.select_one("pre#chordsPre")
        if pre is None:
            return None
        titol = _text(sopa.select_one("h1.s-title")) or _text(sopa.select_one("h1"))
        m = re.match(r"\s*(.*?)\s+-\s+(.*?):\s*Acordes", _text(sopa.select_one("title")))
        artista = (m.group(2) if m else "") or _artista_de_url(url)
        linies = []
        for text, acords in linies_pre(pre, "a"):
            linies += separa_seccio(text, acords)
        content = a_content(linies)
        if not content:
            return None
        return TabCrua(lloc=LLOC, url=url, titol=titol, artista=artista, content=content)
    except Exception:  # noqa: BLE001
        log.info("AcordesWeb: no s'ha pogut llegir %s", url, exc_info=True)
        return None


def baixa(c: Candidat) -> TabCrua | None:
    try:
        html = http.obte(c.url)
        return parseja(html, c.url) if html else None
    except Exception:  # noqa: BLE001
        log.info("AcordesWeb: no s'ha pogut baixar %s", c.url, exc_info=True)
        return None
