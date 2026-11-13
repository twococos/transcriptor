"""GuitarTuna (guitartuna.com): transcripcions pròpies, amb la versió "Official" (original) i la
"Simplified" (easy) de cada cançó, seccions amb nom i l'acord a la síl·laba exacta.

- Cerca: les URL porten un id que no es pot deduir del títol
  (/chords/wonderwall-oasis-original-guitar-chords-60b5c03ca597073ccc5707ab; sense l'id, 404), el
  cercador és JavaScript sobre /api/ (prohibit a robots.txt) i els sitemaps de cançons passen de
  2 MB cadascun. Es fa servir l'índex d'artistes: /artists/browse/{lletra} (la primera lletra
  sense "The"; només la primera pàgina, la dels artistes més populars) dona l'URL de l'artista
  (/artists/{slug}-easy-original-guitar-chords-tabs-{id}), i la pàgina de l'artista llista totes
  les cançons (`[data-testid=collection-table-row]`) amb els enllaços "original" i "simplified".
  Són dues pàgines d'uns 600–800 kB per cerca; un artista poc popular no es troba.
- Tab: port de src/lib/importers/guitartuna.ts del canconer. Metadades al JSON-LD
  `MusicComposition` (name, composer.name, musicalKey, text amb "Capo: fret 2"). El cos és
  `#songcontent`: `.part_type` és el nom de la secció i cada `.line` una línia, amb un
  `.beat_info` per temps (`data-chord` si hi ha acord, `--w:N` l'amplada en caràcters) i la
  lletra en un `<div>` on cada acord deixa un `<span class="sr-only">` a la seva posició. El
  format antic (`.chordLabel` i `calc(var(--font-width) * N)`) també es llegeix.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .. import http
from ..model import Candidat, TabCrua
from ..text_pla import fusiona
from . import acceptable, pla, puntuacio, slug

log = logging.getLogger(__name__)

LLOC = "guitartuna"
ARREL = "https://guitartuna.com"
MAXIM = 2
_RE_CANCO = re.compile(r"/chords/([a-z0-9-]+?)-(easy|original)-guitar-chords-([0-9a-f]{24})")
_RE_ARTISTA = re.compile(r"/artists/([a-z0-9-]+?)-easy-original-guitar-chords-tabs-[0-9a-f]{24}")


# ── Cerca ──────────────────────────────────────────────────────────────────────────────────────

def _slugs_artista(artista: str) -> set[str]:
    sense_apostrofs = re.sub(r"['’`´]", "", artista)
    return {s.removeprefix("the-") for s in (slug(artista), slug(sense_apostrofs)) if s}


def url_browse(artista: str) -> str | None:
    p = pla(artista).removeprefix("the ")
    if not p:
        return None
    return f"{ARREL}/artists/browse/{'0-9' if p[0].isdigit() else p[0]}"


def url_artista(html: str, artista: str) -> str | None:
    """De la pàgina /artists/browse/{lletra}, l'URL de l'artista (slug igual, amb o sense "the")."""
    slugs = _slugs_artista(artista)
    for m in _RE_ARTISTA.finditer(html):
        if m.group(1).removeprefix("the-") in slugs:
            return urljoin(ARREL, m.group(0))
    return None


def cancons_artista(html: str) -> list[dict]:
    """Pàgina d'artista → [{titol, artista, original, easy}] (URL absolutes o None)."""
    sopa = BeautifulSoup(html, "html.parser")
    nom = ""
    for s in sopa.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string or "")
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "MusicGroup":
            nom = d.get("name") or ""
            break
    sortida = []
    for fila in sopa.select('[data-testid="collection-table-row"]'):
        t = fila.select_one('[data-testid="collection-table-row-name"]')
        a_artista = fila.select_one('[data-testid="collection-table-row-artist"]')
        urls = {}
        for a in fila.select("a[href]"):
            m = _RE_CANCO.search(a["href"])
            if m:
                urls.setdefault(m.group(2), urljoin(ARREL, m.group(0)))
        if t and urls:
            sortida.append({"titol": " ".join(t.get_text(" ").split()),
                            "artista": (a_artista.get_text(" ", strip=True) if a_artista else "") or nom,
                            "original": urls.get("original"), "easy": urls.get("easy")})
    return sortida


def cerca(titol: str, artista: str, idioma: str | None = None) -> list[Candidat]:
    try:
        browse = url_browse(artista)
        html = http.obte(browse) if browse else None
        url = url_artista(html, artista) if html else None
        html = http.obte(url) if url else None
        if not html:
            return []
        cancons = [c for c in cancons_artista(html) if acceptable(titol, artista, c["titol"], c["artista"])]
        cancons.sort(key=lambda c: -puntuacio(titol, artista, c["titol"], c["artista"]))
        sortida = []
        for c in cancons:
            # Primer la versió original (els acords del disc) i després la simplificada
            for versio, clau in ((1, "original"), (2, "easy")):
                if c[clau]:
                    sortida.append(Candidat(lloc=LLOC, url=c[clau], titol=c["titol"], artista=c["artista"],
                                            versio=versio, extra={"tipus": clau}))
        return sortida[:MAXIM]
    except Exception:  # noqa: BLE001
        log.info("GuitarTuna: la cerca ha fallat", exc_info=True)
        return []


# ── Tab ────────────────────────────────────────────────────────────────────────────────────────

def _metadades(sopa: BeautifulSoup) -> dict:
    for s in sopa.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string or "")
        except ValueError:
            continue
        for it in d if isinstance(d, list) else [d]:
            if isinstance(it, dict) and it.get("@type") == "MusicComposition":
                return it
    return {}


def _to(clau: str) -> str | None:
    """"F# minor" → "F#m", "C major" → "C"."""
    m = re.fullmatch(r"\s*([A-G][#b]?)\s*(major|maj|minor|min|m)?\s*", clau or "", re.I)
    if not m:
        return None
    return m.group(1) + ("m" if (m.group(2) or "").lower() in ("minor", "min", "m") else "")


def _amplada(estil: str, prop: str) -> float:
    if prop == "width":
        m = re.search(r"--w\s*:\s*(\d+(?:\.\d+)?)", estil)
        if m:
            return float(m.group(1))
    m = re.search(rf"(?<![-\w]){prop}\s*:\s*calc\(\s*var\(--font-width\)\s*\*\s*(\d+(?:\.\d+)?)", estil)
    return float(m.group(1)) if m else 0.0


def _lletra(linia: Tag) -> tuple[str, list[int]]:
    """La lletra de la línia i les posicions on hi ha un acord (`span.sr-only`)."""
    for div in linia.find_all("div", recursive=False):
        if div.find(class_="beat_info"):
            continue
        trossos: list[str] = []
        marques: list[int] = []

        def visita(node: Tag) -> None:
            for fill in node.children:
                if isinstance(fill, Tag):
                    if "sr-only" in (fill.get("class") or []):
                        marques.append(len("".join(trossos)))
                    else:
                        visita(fill)
                elif isinstance(fill, NavigableString) and not isinstance(fill, Comment):
                    trossos.append(str(fill))

        visita(div)
        text = "".join(trossos).replace(" ", " ")
        if text.strip() or marques:
            return _sense_farciment(text, marques)
    return "", []


def _sense_farciment(text: str, marques: list[int]) -> tuple[str, list[int]]:
    """La web allarga la lletra amb espais perquè hi càpiguen els acords ("gonna    throw"); al
    content l'acord no ocupa amplada, així que els espais seguits es redueixen a un."""
    net, nova = "", []
    for i, c in enumerate(text):
        nova.append(len(net))
        if not (c == " " and net.endswith(" ")):
            net += c
    nova.append(len(net))
    return net, [nova[m] for m in marques]


def _linia(linia: Tag) -> str | None:
    acords, col = [], 0.0
    for beat in linia.select(".beat_info"):
        estil = beat.get("style") or ""
        marge, ample = _amplada(estil, "margin-left"), _amplada(estil, "width")
        etiqueta = beat.find(attrs={"data-chord": True})
        if etiqueta is not None:
            nom = etiqueta["data-chord"]
        else:
            etiqueta = beat.select_one(".chordLabel")
            nom = etiqueta.get_text() if etiqueta else ""
        nom = "".join(nom.split())
        if nom:
            acords.append((round(col + marge), nom))
        col += marge + ample
    text, marques = _lletra(linia)
    if text.strip() and len(marques) == len(acords):
        acords = [(m, a) for m, (_, a) in zip(marques, acords)]
    if not acords:
        return text.rstrip() or None
    return fusiona(acords, text if text.strip() else None)


def parseja(html: str, url: str) -> TabCrua | None:
    try:
        sopa = BeautifulSoup(html, "html.parser")
        canco = sopa.select_one("#songcontent")
        if canco is None:
            return None
        meta = _metadades(sopa)
        titol = re.sub(r"\s*\((chords?|cifra|acordes?|tabs?)\)\s*$", "", meta.get("name") or "", flags=re.I)
        if not titol:
            h1 = sopa.select_one('[data-testid="song-title"]') or sopa.select_one("h1")
            titol = h1.get_text(" ", strip=True) if h1 else ""
        compositor = meta.get("composer")
        artista = compositor.get("name", "") if isinstance(compositor, dict) else ""
        text_meta = meta.get("text") or ""
        m = re.search(r"Capo:\s*(?:fret\s*)?(\d+)", text_meta, re.I)
        capo = int(m.group(1)) if m and int(m.group(1)) <= 12 else 0

        sortida = []
        for el in canco.find_all(class_=["part_type", "line"]):
            classes = el.get("class") or []
            if "part_type" in classes:
                nom = " ".join(el.get_text(" ").split())
                if nom:
                    sortida.append(f"<sec>{nom}</sec>")
            elif "line" in classes and not el.find_parent(class_="line"):
                l = _linia(el)
                if l and l.strip():
                    sortida.append(l)
        content = "\n".join(sortida)
        if "<ch>" not in content:
            return None
        return TabCrua(lloc=LLOC, url=url, titol=titol.strip(), artista=artista.strip(), content=content,
                       capo=capo, to=_to(meta.get("musicalKey") or ""),
                       versio=2 if "-easy-guitar-chords-" in url else 1)
    except Exception:  # noqa: BLE001
        log.info("GuitarTuna: no s'ha pogut llegir %s", url, exc_info=True)
        return None


def baixa(c: Candidat) -> TabCrua | None:
    try:
        html = http.obte(c.url)
        return parseja(html, c.url) if html else None
    except Exception:  # noqa: BLE001
        log.info("GuitarTuna: no s'ha pogut baixar %s", c.url, exc_info=True)
        return None
