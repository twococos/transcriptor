"""LaCuerda (acordes.lacuerda.net): molt repertori en castellà i força en català. Les valoracions
no surten a l'HTML (les carrega el JavaScript), però la pàgina de la cançó ordena les versions.

- Cerca: https://acordes.lacuerda.net/busca.php?canc=0&exp=<títol artista>. Cada resultat és un
  `<li id="rNNN" lcd="TTRTRBT-1234567">Títol</li>` dins la fila de l'artista, i els arrays JS
  `var hds=[...]` i `var fns=[...]` donen els slugs d'artista i de cançó. L'índex canvia a cada
  petició: és `n` o `NMAX-n` segons digui la funció `lOpen` de la mateixa pàgina, que es llegeix.
  `lcd` diu el tipus de cada versió (R = lletra i acords, T = tablatura, B = baix). Es busca
  "títol artista" i, si no surt res, només el títol (si l'artista no hi és, el cercador no troba
  res amb el nom posat; tampoc no té gaire música en anglès). Després es baixa la pàgina de la
  cançó (https://acordes.lacuerda.net/{hd}/{fn}), que llista les versions (`#rThumbs li` amb
  `.tiR` i l'enllaç `{fn}-N.shtml`) en l'ordre de la web.
- Versió: `{fn}.shtml` (la 1) o `{fn}-N.shtml`. Títol i artista a `#tH1 h1/h2`; la tab és el
  `<pre>` de `#t_body`, amb cada acord en un `<a>` a la línia de sobre de la lletra. No hi ha
  seccions marcades: només les que escriu qui la transcriu ("Intro", "CORO:", "[Estribillo]").
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .. import http
from ..model import Candidat, TabCrua
from ..text_pla import RE_SECCIO, RE_SECCIO_DOS_PUNTS, RE_SOBRANT, a_content
from . import acceptable, puntuacio

log = logging.getLogger(__name__)

LLOC = "lacuerda"
ARREL = "https://acordes.lacuerda.net"
URL_CERCA = ARREL + "/busca.php"
MAXIM = 2
_RE_CAPO = re.compile(r"(?:cejilla|capo(?:traste)?)\D{0,15}?(\d{1,2})", re.I)

Linia = tuple[str, list[tuple[int, str]]]  # (text amb els acords canviats per espais, [(columna, acord)])


# ── Cerca ──────────────────────────────────────────────────────────────────────────────────────

def _array_js(html: str, nom: str) -> list[str]:
    m = re.search(rf"var {nom}\s*=\s*\[(.*?)\];", html, re.S)
    return re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1)) if m else []


def _index_js(html: str, nom: str, n: int, nmax: int) -> int:
    """La pàgina ordena els arrays a l'atzar: `lOpen` diu si cal `hds[n]` o `hds[NMAX-n]`."""
    m = re.search(r"function lOpen\([^)]*\)\s*\{([^}]*)\}", html)
    return nmax - n if m and re.search(rf"{nom}\[\s*NMAX\s*-\s*n\s*\]", m.group(1)) else n


def resultats_cerca(html: str) -> list[dict]:
    """Resultats de busca.php: [{hd, fn, titol, artista, tipus, versions: [(n, tipus)]}]."""
    hds, fns = _array_js(html, "hds"), _array_js(html, "fns")
    m = re.search(r"var NMAX\s*=\s*(\d+)", html)
    nmax = int(m.group(1)) if m else len(hds) - 1
    sopa = BeautifulSoup(html, "html.parser")
    sortida = []
    for fila in sopa.select("#s_main tr"):
        a_art = fila.select_one("td a")
        artista = a_art.get_text(" ", strip=True) if a_art else ""
        for li in fila.select("li[id]"):
            m = re.fullmatch(r"r(\d+)", li["id"])
            if not m:
                continue
            i, j = _index_js(html, "hds", int(m.group(1)), nmax), _index_js(html, "fns", int(m.group(1)), nmax)
            if not (0 <= i < len(hds) and 0 <= j < len(fns)):
                continue
            tipus, _, nums = (li.get("lcd") or "").partition("-")
            # Una lletra i una xifra per versió; amb més de 9 versions no es pot partir i només
            # serveix per saber si n'hi ha cap de lletra i acords
            versions = list(zip((int(d) for d in nums), tipus)) if len(nums) == len(tipus) else []
            sortida.append({"hd": hds[i], "fn": fns[j], "titol": li.get_text(" ", strip=True),
                            "artista": artista, "tipus": tipus, "versions": versions})
    return sortida


def url_versio(hd: str, fn: str, n: int) -> str:
    return f"{ARREL}/{hd}/{fn}.shtml" if n <= 1 else f"{ARREL}/{hd}/{fn}-{n}.shtml"


def versions_index(html: str, url: str) -> list[tuple[int, str]]:
    """Versions de lletra i acords (R) de la pàgina de la cançó, en l'ordre de la web: [(n, url)]."""
    sopa = BeautifulSoup(html, "html.parser")
    sortida = []
    for li in sopa.select("#rThumbs li"):
        a = li.select_one(".rtLabel a[href]")
        if not a or not li.select_one(".tiR"):
            continue
        m = re.search(r"-(\d+)\.shtml$", a["href"])
        sortida.append((int(m.group(1)) if m else 1, urljoin(url, a["href"])))
    return sortida


def _titol_index(html: str) -> str:
    h1 = BeautifulSoup(html, "html.parser").select_one("#r_head h1")
    return (h1.find(string=True, recursive=False) or "") if h1 else ""


def cerca(titol: str, artista: str, idioma: str | None = None) -> list[Candidat]:
    try:
        cancons = []
        for consulta in dict.fromkeys([f"{titol} {artista}".strip(), titol]):
            html = http.obte(URL_CERCA, {"canc": "0", "exp": consulta})
            cancons = [r for r in resultats_cerca(html or "")
                       if "R" in r["tipus"] and acceptable(titol, artista, r["titol"], r["artista"])]
            if cancons:
                break
        cancons.sort(key=lambda r: -puntuacio(titol, artista, r["titol"], r["artista"]))
        sortida: list[Candidat] = []
        for r in cancons:
            url_canco = f"{ARREL}/{r['hd']}/{r['fn']}"
            index = http.obte(url_canco)
            titol_index = _titol_index(index) if index else ""
            if titol_index and not acceptable(titol, "", titol_index, ""):
                log.info("LaCuerda: %s no és %s", url_canco, titol)  # per si la web torna a canviar els índexs
                continue
            versions = versions_index(index, url_canco) if index else []
            if not versions:
                versions = [(n, url_versio(r["hd"], r["fn"], n)) for n, t in r["versions"] if t == "R"]
            sortida += [Candidat(lloc=LLOC, url=u, titol=r["titol"], artista=r["artista"], versio=n)
                        for n, u in versions]
            if len(sortida) >= MAXIM:
                break
        return sortida[:MAXIM]
    except Exception:  # noqa: BLE001
        log.info("LaCuerda: la cerca ha fallat", exc_info=True)
        return []


# ── Tab ────────────────────────────────────────────────────────────────────────────────────────

def linies_pre(pre: Tag, etiqueta: str = "a") -> list[Linia]:
    """Línies del <pre>: el text sense els acords (al seu lloc hi queden espais) i els acords
    (el text de cada `<etiqueta>`; Cifra Club també ho fa servir, amb `<b>`)."""
    linies: list[Linia] = [("", [])]

    def afegeix(text: str, acord: bool) -> None:
        for i, tros in enumerate(text.replace("\r", "").replace("\t", "    ").split("\n")):
            if i:
                linies.append(("", []))
            actual, acords = linies[-1]
            if acord:
                acords = acords + [(len(actual) + m.start(), m.group(0)) for m in re.finditer(r"\S+", tros)]
                tros = " " * len(tros)
            linies[-1] = (actual + tros, acords)

    def visita(node: Tag) -> None:
        for fill in node.children:
            if isinstance(fill, Comment):
                continue
            if isinstance(fill, NavigableString):
                afegeix(str(fill), False)
            elif fill.name == etiqueta:
                afegeix(fill.get_text(), True)
            elif fill.name == "br":
                afegeix("\n", False)
            else:
                visita(fill)

    visita(pre)
    return linies


def separa_seccio(text: str, acords: list[tuple[int, str]]) -> list[Linia]:
    """"Intro   Am  E7" o "[Coro] Am": la secció en una línia i els acords sols en una altra."""
    if not acords:
        return [(text, acords)]
    nom = None
    m = RE_SECCIO.match(text)
    if m and RE_SOBRANT.match(m.group(2).strip()):
        nom, fi = m.group(1).strip(), m.end(1) + 1
    else:
        m = re.match(r"\s*([^:]+?)\s*(?::|\s{2,}|$)", text)
        if m and RE_SECCIO_DOS_PUNTS.match(m.group(1)) and RE_SOBRANT.match(text[m.end():].strip()):
            nom, fi = m.group(1), m.end(1)
    if nom is None or min(c for c, _ in acords) < fi:
        return [(text, acords)]
    inici = min(c for c, _ in acords)
    # La línia en blanc del final evita que els acords de la intro es fusionin amb la lletra següent
    return [(f"[{nom}]", []), (text[inici:], [(c - inici, a) for c, a in acords]), ("", [])]


def parseja(html: str, url: str) -> TabCrua | None:
    try:
        sopa = BeautifulSoup(html, "html.parser")
        pre = sopa.select_one("#t_body pre")
        if pre is None:
            return None
        h1 = sopa.select_one("#tH1 h1 a") or sopa.select_one("#tH1 h1")
        h2 = sopa.select_one("#tH1 h2 a") or sopa.select_one("#tH1 h2")
        linies: list[Linia] = []
        for text, acords in linies_pre(pre):
            linies += separa_seccio(text, acords)
        content = a_content(linies)
        if not content:
            return None
        m = _RE_CAPO.search(pre.get_text())
        capo = int(m.group(1)) if m and 0 < int(m.group(1)) <= 12 else 0
        v = re.search(r"-(\d+)\.shtml", url)
        return TabCrua(lloc=LLOC, url=url, titol=h1.get_text(" ", strip=True) if h1 else "",
                       artista=h2.get_text(" ", strip=True) if h2 else "", content=content, capo=capo,
                       versio=int(v.group(1)) if v else 1)
    except Exception:  # noqa: BLE001
        log.info("LaCuerda: no s'ha pogut llegir %s", url, exc_info=True)
        return None


def baixa(c: Candidat) -> TabCrua | None:
    try:
        url, html = c.url, http.obte(c.url)
        if html and "t_body" not in html and "rThumbs" in html:
            # Pàgina de la cançó (URL afegida a mà): la primera versió de lletra i acords
            versions = versions_index(html, url)
            if not versions:
                return None
            url = versions[0][1]
            html = http.obte(url)
        return parseja(html, url) if html else None
    except Exception:  # noqa: BLE001
        log.info("LaCuerda: no s'ha pogut baixar %s", c.url, exc_info=True)
        return None
