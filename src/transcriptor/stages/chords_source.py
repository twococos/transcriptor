"""Etapa chords_source: tabs d'acords de la cançó a diverses pàgines (vegeu fonts/).

Es busca a tots els llocs alhora (un fil per lloc; Ultimate Guitar amb el navegador sense
finestra, si n'hi ha) i es baixen les versions que semblen la cançó. Les URL afegides a mà des de
l'admin es baixen sempre; les bloquejades, mai. Mai fa fallar la feina: sense xarxa o sense
resultats, la llista és buida i l'anàlisi és la de l'àudio sol.
"""

from __future__ import annotations

import importlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from ..fonts import navegador
from ..fonts.model import Candidat, TabCrua

log = logging.getLogger(__name__)

VERSIO = 1  # canvia-la si canvia la cerca o el parseig (invalida la cache)
LLOCS = ["ultimate_guitar", "cifraclub", "lacuerda", "guitartuna", "acordscatala"]
DOMINIS = {"ultimate-guitar.com": "ultimate_guitar", "cifraclub.com": "cifraclub", "cifraclub.com.br": "cifraclub",
           "lacuerda.net": "lacuerda", "guitartuna.com": "guitartuna", "acordscatala.cat": "acordscatala"}
LIMIT_S = 120  # temps màxim de tota la cerca


def _modul(lloc: str):
    try:
        return importlib.import_module(f"..fonts.llocs.{lloc}", __package__)
    except ImportError:
        return None


def lloc_de_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    return next((l for d, l in DOMINIS.items() if host == d or host.endswith("." + d)), None)


def _cerca_lloc(lloc: str, titol: str, artista: str, idioma: str | None, bloquejades: set[str],
                nav) -> list[TabCrua]:
    m = _modul(lloc)
    if m is None:
        return []
    extra = {"nav": nav} if lloc == "ultimate_guitar" else {}
    try:
        candidats = [c for c in m.cerca(titol, artista, idioma, **extra) if c.url not in bloquejades]
        tabs = [m.baixa(c, **extra) for c in candidats]
    except Exception:  # noqa: BLE001 — un lloc que falla no ha d'aturar els altres
        log.info("Fonts d'acords: %s ha fallat", lloc, exc_info=True)
        return []
    return [t for t in tabs if t is not None and t.content.count("<ch>") >= 4]


def _baixa_url(url: str, nav) -> TabCrua | None:
    lloc = lloc_de_url(url)
    m = _modul(lloc) if lloc else None
    if m is None:
        log.info("Fonts d'acords: no sé llegir %s", url)
        return None
    extra = {"nav": nav} if lloc == "ultimate_guitar" else {}
    try:
        tab = m.baixa(Candidat(lloc=lloc, url=url, titol="", artista=""), **extra)
    except Exception:  # noqa: BLE001
        log.info("Fonts d'acords: %s ha fallat", url, exc_info=True)
        return None
    if tab:
        tab.manual = True
    return tab


def obte(titol: str, artista: str, idioma: str | None = None, urls_extra: list[str] | None = None,
         bloquejades: list[str] | None = None, llocs: list[str] | None = None) -> list[TabCrua]:
    """Tabs trobades (sense repetir URL). Les manuals primer."""
    if not titol:
        return []
    llocs = llocs or LLOCS
    bloq = set(bloquejades or [])
    inici = time.monotonic()
    usa_nav = navegador.disponible() and ("ultimate_guitar" in llocs or any(
        lloc_de_url(u) == "ultimate_guitar" for u in urls_extra or []))
    nav_ctx = navegador.Navegador() if usa_nav else None
    try:
        nav = nav_ctx.__enter__() if nav_ctx else None
    except Exception:  # noqa: BLE001
        log.info("Fonts d'acords: el navegador no s'ha pogut obrir", exc_info=True)
        nav, nav_ctx = None, None
    try:
        with ThreadPoolExecutor(max_workers=len(llocs) + 1) as ex:
            manuals = ex.submit(lambda: [t for u in urls_extra or [] if u not in bloq
                                         for t in [_baixa_url(u, nav)] if t])
            futurs = [ex.submit(_cerca_lloc, l, titol, artista, idioma, bloq, nav) for l in llocs
                      if l != "ultimate_guitar" or nav is not None]
            tabs = list(manuals.result(timeout=LIMIT_S))
            for f in futurs:
                try:
                    tabs.extend(f.result(timeout=max(1.0, LIMIT_S - (time.monotonic() - inici))))
                except Exception:  # noqa: BLE001 — inclou el temps esgotat
                    log.info("Fonts d'acords: una cerca no ha acabat a temps")
    finally:
        if nav_ctx:
            nav_ctx.__exit__(None, None, None)
    vistes, sortida = set(), []
    for t in tabs:
        if t.url not in vistes:
            vistes.add(t.url)
            sortida.append(t)
    log.info("Fonts d'acords: %d tabs (%s) en %.0f s", len(sortida),
             ", ".join(sorted({t.lloc for t in sortida})) or "cap", time.monotonic() - inici)
    return sortida
