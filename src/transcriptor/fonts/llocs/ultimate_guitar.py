"""Ultimate Guitar: la font amb més tabs i amb valoracions. Darrere del repte de Cloudflare: cal el
navegador sense finestra (navegador.py).

- Cerca: https://www.ultimate-guitar.com/search.php?search_type=title&value=<artista títol>. La
  pàgina porta les dades a l'atribut `data-content` de `.js-store` (o a `window.UGAPP.store`):
  `store.page.data.results`, amb `type` ("Chords"), `song_name`, `artist_name`, `rating`, `votes`,
  `version` i `tab_url`.
- Tab: el mateix JSON a la pàgina de la tab; `tab_view.wiki_tab.content` és text pla amb els acords
  marcats amb [ch]…[/ch], línies dins [tab]…[/tab] i seccions "[Verse 1]". `tab_view.meta` porta
  el capo i la tonalitat.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
import urllib.parse

from ..model import Candidat, TabCrua
from ..navegador import Navegador
from ..text_pla import a_content
from . import acceptable, puntuacio

log = logging.getLogger(__name__)

LLOC = "ultimate_guitar"
VERSIONS = 3  # es baixen fins a tres versions: el consens entre elles també compta
URL_CERCA = "https://www.ultimate-guitar.com/search.php?search_type=title&value={}"
EXPRESSIO_STORE = (
    "(document.querySelector('.js-store') && document.querySelector('.js-store').getAttribute('data-content'))"
    " || (window.UGAPP && window.UGAPP.store && window.UGAPP.store.page"
    " && JSON.stringify({store: window.UGAPP.store}))")
_RE_CH = re.compile(r"\[ch\](.*?)\[/ch\]")


def _dades(text: str) -> dict | None:
    """`store.page.data` d'un JSON del store o d'un HTML amb `.js-store`."""
    if not text:
        return None
    t = text.lstrip()
    if not t.startswith("{"):
        m = re.search(r'class="js-store"[^>]*data-content="([^"]*)"', text)
        if not m:
            return None
        t = html_mod.unescape(m.group(1))
    try:
        return json.loads(t)["store"]["page"]["data"]
    except (ValueError, KeyError, TypeError):
        return None


def candidats(dades: dict, titol: str, artista: str) -> list[Candidat]:
    sortida = []
    for r in dades.get("results") or []:
        if r.get("type") != "Chords" or not r.get("tab_url") or r.get("marketing_type"):
            continue
        c = Candidat(lloc=LLOC, url=r["tab_url"], titol=r.get("song_name") or "", artista=r.get("artist_name") or "",
                     valoracio=r.get("rating"), vots=r.get("votes"), versio=r.get("version"))
        if acceptable(titol, artista, c.titol, c.artista):
            sortida.append(c)
    sortida.sort(key=lambda c: (-round(puntuacio(titol, artista, c.titol, c.artista), 1), -(c.vots or 0)))
    return sortida[:VERSIONS]


def cerca(titol: str, artista: str, idioma: str | None = None, nav: Navegador | None = None) -> list[Candidat]:
    if nav is None:
        return []
    try:
        q = urllib.parse.quote(f"{artista} {titol}".strip())
        dades = _dades(nav.avalua(URL_CERCA.format(q), EXPRESSIO_STORE) or "")
        return candidats(dades, titol, artista) if dades else []
    except Exception:  # noqa: BLE001
        log.info("Ultimate Guitar: la cerca ha fallat", exc_info=True)
        return []


def content_de_wiki(wiki: str) -> str:
    linies = []
    for l in wiki.replace("\r", "").split("\n"):
        l = l.replace("[tab]", "").replace("[/tab]", "")
        acords, text, cursor = [], "", 0
        for tros in re.split(r"(\[ch\].*?\[/ch\])", l):
            m = _RE_CH.fullmatch(tros)
            if m:
                acords.append((len(text), m.group(1).strip()))
                text += " " * len(m.group(1))
            else:
                text += tros
        linies.append((text, acords))
    return a_content(linies)


def parseja(text: str, url: str) -> TabCrua | None:
    dades = _dades(text)
    if not dades:
        return None
    vista = dades.get("tab_view") or {}
    wiki = (vista.get("wiki_tab") or {}).get("content")
    if not wiki:
        return None
    tab = dades.get("tab") or {}
    meta = vista.get("meta") if isinstance(vista.get("meta"), dict) else {}
    try:
        capo = int(meta.get("capo") or 0)
    except (TypeError, ValueError):
        capo = 0
    return TabCrua(lloc=LLOC, url=url, titol=tab.get("song_name") or "", artista=tab.get("artist_name") or "",
                   content=content_de_wiki(wiki), capo=capo, to=meta.get("tonality") or tab.get("tonality_name") or None,
                   valoracio=tab.get("rating"), vots=tab.get("votes"), versio=tab.get("version"))


def baixa(c: Candidat, nav: Navegador | None = None) -> TabCrua | None:
    if nav is None:
        return None
    try:
        tab = parseja(nav.avalua(c.url, EXPRESSIO_STORE) or "", c.url)
    except Exception:  # noqa: BLE001
        log.info("Ultimate Guitar: %s no s'ha pogut llegir", c.url, exc_info=True)
        return None
    if tab and not tab.vots and c.vots:
        tab.valoracio, tab.vots, tab.versio = c.valoracio, c.vots, c.versio
    return tab
