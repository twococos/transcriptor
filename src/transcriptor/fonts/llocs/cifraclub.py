"""Cifra Club (www.cifraclub.com.br, i en castellà www.cifraclub.com): molt repertori brasiler i
internacional, una versió principal per cançó.

- Cerca: el cercador de la web és un Google personalitzat (no és usable sense navegador), però les
  URL són previsibles: https://www.cifraclub.com.br/{slug-artista}/{slug-títol}/ (provant també
  l'artista sense "the-" i sense apòstrofs, i www.cifraclub.com). Una URL només és un candidat si
  la pàgina existeix i el títol i l'artista que hi surten quadren; l'HTML es desa a
  `extra["html"]` perquè `baixa` no la torni a demanar.
  ATENCIÓ (2026-11): Cifra Club és darrere d'Akamai i respon 403 a `http.obte` fins i tot amb les
  capçaleres de navegador (també a la portada), així que ara mateix la cerca no troba res.
- Tab: port de src/lib/importers/cifraclub.ts del canconer. Títol a `h1.t1`, artista al
  `<title>` ("Cançó - Artista - Cifra Club"), to a `#cifra_tom a`, capo a `#cifra_capo`. La tab és
  el `<pre>` de `.cifra_cnt`, amb cada acord en un `<b>` a la línia de sobre de la lletra i les
  seccions com a "[Refrão]" (o "[Intro] A  D", secció i acords junts) a l'inici de línia.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .. import http
from ..model import Candidat, TabCrua
from ..text_pla import a_content
from . import acceptable, slug
from .lacuerda import linies_pre, separa_seccio

log = logging.getLogger(__name__)

LLOC = "cifraclub"
ARRELS = ("https://www.cifraclub.com.br", "https://www.cifraclub.com")


def _text(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def urls_candidates(titol: str, artista: str) -> list[str]:
    """URL per slug a provar, en ordre (com a molt quatre: cada una és una petició)."""
    sense = lambda t: re.sub(r"['’`´]", "", t)  # noqa: E731 — "Don't" → "dont", com fa la web
    artistes = list(dict.fromkeys(a for a in (slug(sense(artista)), slug(sense(artista)).removeprefix("the-"),
                                              slug(artista)) if a))
    titols = list(dict.fromkeys(t for t in (slug(sense(titol)), slug(titol)) if t))
    if not artistes or not titols:
        return []
    urls = [f"{ARRELS[0]}/{a}/{t}/" for a in artistes for t in titols]
    return list(dict.fromkeys(urls[:3] + [f"{ARRELS[1]}/{artistes[0]}/{titols[0]}/"]))


def cerca(titol: str, artista: str, idioma: str | None = None) -> list[Candidat]:
    try:
        for url in urls_candidates(titol, artista):
            html = http.obte(url)
            tab = parseja(html, url) if html else None
            if tab and acceptable(titol, artista, tab.titol, tab.artista):
                return [Candidat(lloc=LLOC, url=url, titol=tab.titol, artista=tab.artista, extra={"html": html})]
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
        pre = sopa.select_one(".cifra_cnt pre") or sopa.select_one("pre")
        if pre is None:
            return None
        titol = _text(sopa.select_one("h1.t1")) or _text(sopa.select_one("h1"))
        artista = (_artista_de_titol(_text(sopa.select_one("title"))) or _text(sopa.select_one("h2.t3"))
                   or _artista_de_url(url))
        linies = []
        for text, acords in linies_pre(pre, "b"):
            linies += separa_seccio(text, acords)
        content = a_content(linies)
        if not content:
            return None
        m = re.search(r"(\d+)", _text(sopa.select_one("#cifra_capo")))
        capo = int(m.group(1)) if m and int(m.group(1)) <= 12 else 0
        to = _text(sopa.select_one("#cifra_tom a")).replace(" ", "") or None
        return TabCrua(lloc=LLOC, url=url, titol=titol, artista=artista, content=content, capo=capo, to=to)
    except Exception:  # noqa: BLE001
        log.info("Cifra Club: no s'ha pogut llegir %s", url, exc_info=True)
        return None


def baixa(c: Candidat) -> TabCrua | None:
    try:
        html = c.extra.get("html") or http.obte(c.url)
        return parseja(html, c.url) if html else None
    except Exception:  # noqa: BLE001
        log.info("Cifra Club: no s'ha pogut baixar %s", c.url, exc_info=True)
        return None
