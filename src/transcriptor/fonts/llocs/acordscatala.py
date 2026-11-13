"""Acords Català (www.acordscatala.cat): només música en català, amb els acords en solfeig (DO, REm,
SOL#m...), que es deixen tal com surten (els passa a lletres normalitza.py).

- Cerca (només si l'idioma és català o no se sap): no té cercador usable, però la pàgina d'artista
  https://www.acordscatala.cat/ca/{slug-artista} llista totes les cançons
  (`section.info_grup .cancons_grup li a`: títol, `<br>`, `<span>` amb l'àlbum). Es tria el títol
  amb `acceptable`. Com al generador de CSV del canconer (api/admin/scrape-artist).
- Tab: port de src/lib/importers/acordscatala.ts del canconer. Títol a `#canco h1`, artista a
  `h2.nom_grup`, i la tab al `<pre>` de `.canco-container`: cada `<u>` és un tros de línia
  d'acords (pot acabar a la línia següent) i el `<strong>` marca les tornades. Com que no hi ha
  noms de secció, es posa `<sec>Tornada</sec>` en entrar en negreta i `<sec>Estrofa N</sec>` en
  sortir-ne.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .. import http
from ..model import Candidat, TabCrua
from ..text_pla import a_content
from . import acceptable, puntuacio, slug

log = logging.getLogger(__name__)

LLOC = "acordscatala"
ARREL = "https://www.acordscatala.cat"
MAXIM = 2
_TIPOGRAFICS = str.maketrans({"’": "'", "‘": "'", "‚": "'", "“": '"', "”": '"', "„": '"', "\xa0": " "})


def _net(text: str) -> str:
    return " ".join(text.translate(_TIPOGRAFICS).split())


# ── Cerca ──────────────────────────────────────────────────────────────────────────────────────

def cancons_artista(html: str, url: str) -> tuple[str, list[tuple[str, str]]]:
    """Pàgina d'artista → (nom de l'artista, [(títol, url de la cançó)])."""
    sopa = BeautifulSoup(html, "html.parser")
    seccio = sopa.select_one("section.info_grup")
    if seccio is None:
        return "", []
    h1 = seccio.select_one(".header_grup h1")
    cancons = []
    for a in seccio.select(".cancons_grup li a[href]"):
        # El títol és el text de l'<a> abans del <br> i el <span> de l'àlbum
        trossos = []
        for fill in a.children:
            if isinstance(fill, Tag) and fill.name in ("br", "span"):
                break
            trossos.append(fill.get_text() if isinstance(fill, Tag) else str(fill))
        titol = _net("".join(trossos))
        if titol:
            cancons.append((titol, urljoin(url, a["href"])))
    return (_net(h1.get_text()) if h1 else ""), cancons


def cerca(titol: str, artista: str, idioma: str | None = None) -> list[Candidat]:
    if idioma not in (None, "ca") or not artista:
        return []
    try:
        slugs = dict.fromkeys([slug(re.sub(r"['’`´]", "", artista)), slug(artista)])
        for s in slugs:
            if not s:
                continue
            url = f"{ARREL}/ca/{s}"
            html = http.obte(url)
            if not html:
                continue
            nom, cancons = cancons_artista(html, url)
            nom = nom or artista
            bones = [(t, u) for t, u in cancons if acceptable(titol, artista, t, nom)]
            bones.sort(key=lambda tu: -puntuacio(titol, artista, tu[0], nom))
            return [Candidat(lloc=LLOC, url=u, titol=t, artista=nom) for t, u in bones[:MAXIM]]
        return []
    except Exception:  # noqa: BLE001
        log.info("Acords Català: la cerca ha fallat", exc_info=True)
        return []


# ── Tab ────────────────────────────────────────────────────────────────────────────────────────

def _linies_pre(pre: Tag) -> list[tuple[str, list[tuple[int, str]], bool]]:
    """Línies del <pre>: (text amb els acords canviats per espais, [(columna, acord)], en negreta).

    Una línia és "en negreta" si la majoria dels caràcters visibles hi són (si empaten, si
    començava dins un <strong>), com fa el TS amb "</strong><u>…</u><strong>"."""
    linies: list[list] = [["", [], 0, 0, False]]  # text, acords, caràcters en negreta, fora, comença en negreta

    def afegeix(text: str, acord: bool, fort: bool) -> None:
        for i, tros in enumerate(text.replace("\r", "").replace("\t", "    ").split("\n")):
            if i:
                linies.append(["", [], 0, 0, fort])
            l = linies[-1]
            if acord:
                l[1] += [(len(l[0]) + m.start(), m.group(0)) for m in re.finditer(r"\S+", tros)]
            visibles = sum(not c.isspace() for c in tros)
            l[2 if fort else 3] += visibles
            l[0] += " " * len(tros) if acord else tros.translate(_TIPOGRAFICS)

    def visita(node: Tag, acord: bool, fort: bool) -> None:
        for fill in node.children:
            if isinstance(fill, Comment):
                continue
            if isinstance(fill, NavigableString):
                afegeix(str(fill), acord, fort)
            elif fill.name == "br":
                afegeix("\n", acord, fort)
            else:
                visita(fill, acord or fill.name == "u", fort or fill.name in ("strong", "b"))

    visita(pre, False, False)
    return [(t, a, f > n or (f == n and inici)) for t, a, f, n, inici in linies]


def _amb_seccions(linies: list[tuple[str, list[tuple[int, str]], bool]]) -> list[tuple[str, list[tuple[int, str]]]]:
    """Afegeix "[Tornada]" en entrar a la negreta i "[Estrofa N]" en sortir-ne (i al començament)."""
    sortida: list[tuple[str, list[tuple[int, str]]]] = []
    actiu, estrofa = None, 0
    for i, (text, acords, fort) in enumerate(linies):
        if not text.strip() and not acords:
            sortida.append(("", []))
            continue
        if acords and not text.strip():
            # Una línia d'acords va amb la secció de la lletra que la segueix
            seguent = linies[i + 1] if i + 1 < len(linies) else None
            if seguent and seguent[0].strip() and not seguent[1]:
                fort = seguent[2]
        if fort != actiu:
            if fort:
                sortida.append(("[Tornada]", []))
            else:
                estrofa += 1
                sortida.append((f"[Estrofa {estrofa}]", []))
            actiu = fort
        sortida.append((text, acords))
    return sortida


def parseja(html: str, url: str) -> TabCrua | None:
    try:
        sopa = BeautifulSoup(html, "html.parser")
        canco = sopa.select_one("#canco")
        if canco is None:
            return None
        pre = canco.select_one(".canco-container pre") or canco.select_one("pre")
        if pre is None:
            return None
        h1, h2 = canco.select_one("h1"), canco.select_one("h2.nom_grup")
        content = a_content(_amb_seccions(_linies_pre(pre)))
        if not content:
            return None
        return TabCrua(lloc=LLOC, url=url, titol=_net(h1.get_text()) if h1 else "",
                       artista=_net(h2.get_text()) if h2 else "", content=content)
    except Exception:  # noqa: BLE001
        log.info("Acords Català: no s'ha pogut llegir %s", url, exc_info=True)
        return None


def baixa(c: Candidat) -> TabCrua | None:
    try:
        html = http.obte(c.url)
        return parseja(html, c.url) if html else None
    except Exception:  # noqa: BLE001
        log.info("Acords Català: no s'ha pogut baixar %s", c.url, exc_info=True)
        return None
