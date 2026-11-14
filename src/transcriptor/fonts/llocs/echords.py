"""E-Chords (www.e-chords.com): web multilingüe gran, amb força repertori català (Txarango, Lluís
Llach, Els Catarres…).

- Cerca: el cercador de la web va per JavaScript, però la pàgina de l'artista
  (https://www.e-chords.com/{slug-artista}, sense protecció) llista totes les cançons amb enllaços
  `/{idioma}/acordes/{artista}/{cançó}` i el títol al text ("Wonderwall", "Wonderwall (ver. 2)").
- Tab: darrere del repte de Cloudflare, amb el navegador sense finestra (navegador.py). És el
  `<pre>` amb cada acord en un `<span data-chord>` a la línia de sobre de la lletra, les seccions en
  `<i>` ("Intro:") i, de vegades, una alternativa simplificada en `<b>` ("(Simplified: Em G D A)"),
  que es treu. Títol a `h1`, artista al primer `h2`, capo a `.capo .hl` ("song.fret 2").
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .. import http
from ..model import Candidat, TabCrua
from ..navegador import Navegador
from ..text_pla import a_content
from . import acceptable, puntuacio, slug
from .lacuerda import linies_pre, separa_seccio

log = logging.getLogger(__name__)

LLOC = "echords"
ARREL = "https://www.e-chords.com"
VERSIONS = 2
EXPRESSIO_HTML = "document.querySelector('pre span[data-chord]') && document.documentElement.outerHTML"
_RE_TAB = re.compile(r"^(?:https://www\.e-chords\.com)?/(?:[a-z]{2}/)?(?:acordes|chords|cifras|accords)/[^/]+/[^/?#]+$")


def _text(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def urls_artista(artista: str) -> list[str]:
    sense = re.sub(r"['’`´]", "", artista)
    slugs = dict.fromkeys(s for s in (slug(sense), slug(sense).removeprefix("the-"), slug(artista)) if s)
    return [f"{ARREL}/{s}" for s in list(slugs)[:2]]


def cancons_artista(html: str) -> tuple[str, list[tuple[str, str]]]:
    """(nom de l'artista, [(títol, url)]) de la pàgina d'un artista."""
    sopa = BeautifulSoup(html, "html.parser")
    cancons = []
    for a in sopa.find_all("a", href=True):
        titol = _text(a)
        if titol and _RE_TAB.match(a["href"]):
            url = a["href"] if a["href"].startswith("http") else ARREL + a["href"]
            cancons.append((titol, url))
    return _text(sopa.find("h1")), list(dict.fromkeys(cancons))


def cerca(titol: str, artista: str, idioma: str | None = None, nav: Navegador | None = None) -> list[Candidat]:
    if not artista:
        return []
    try:
        for url in urls_artista(artista):
            html = http.obte(url)
            if not html:
                continue
            nom, cancons = cancons_artista(html)
            nom = nom or artista
            cs = [Candidat(lloc=LLOC, url=u, titol=t, artista=nom) for t, u in cancons
                  if acceptable(titol, artista, t, nom)]
            if cs:
                cs.sort(key=lambda c: -puntuacio(titol, artista, c.titol, c.artista))
                for v, c in enumerate(cs[:VERSIONS], 1):
                    c.versio = v
                return cs[:VERSIONS]
        return []
    except Exception:  # noqa: BLE001
        log.info("E-Chords: la cerca ha fallat", exc_info=True)
        return []


def parseja(html: str, url: str) -> TabCrua | None:
    try:
        sopa = BeautifulSoup(html, "html.parser")
        pre = next((p for p in sopa.find_all("pre") if p.find("span", attrs={"data-chord": True})), None)
        if pre is None:
            return None
        for b in pre.find_all("b"):
            if re.match(r"\s*\(?\s*simplifi", b.get_text(), re.I):
                b.decompose()
        titol = _text(sopa.find("h1"))
        artista = _text(sopa.find("h2"))
        m = re.match(r"\s*(?:Acordes|Chords|Cifra|Accords)\s+(?:de|of|for)?\s*(.*?)\s+-\s+(.*?)\s*\|", _text(sopa.title))
        if m:
            titol, artista = titol or m.group(1), artista or m.group(2)
        linies = []
        for text, acords in linies_pre(pre, "span"):
            linies += separa_seccio(text, acords)
        content = a_content(linies)
        if not content:
            return None
        m = re.search(r"(\d+)", _text(sopa.select_one(".capo .hl")))
        capo = int(m.group(1)) if m and int(m.group(1)) <= 12 else 0
        return TabCrua(lloc=LLOC, url=url, titol=titol, artista=artista, content=content, capo=capo)
    except Exception:  # noqa: BLE001
        log.info("E-Chords: no s'ha pogut llegir %s", url, exc_info=True)
        return None


def baixa(c: Candidat, nav: Navegador | None = None) -> TabCrua | None:
    if nav is None:
        return None
    try:
        html = nav.avalua(c.url, EXPRESSIO_HTML, limit_s=45)
        tab = parseja(html, c.url) if html else None
        if tab:
            tab.versio = c.versio
        return tab
    except Exception:  # noqa: BLE001
        log.info("E-Chords: no s'ha pogut baixar %s", c.url, exc_info=True)
        return None
