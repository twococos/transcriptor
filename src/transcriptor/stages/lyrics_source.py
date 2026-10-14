"""Etapa lyrics_source: text de la lletra, per ordre de preferència usuari > BD > LRCLIB.

De LRCLIB només n'aprofitem el text i el tall de línies: els seus temps sovint no quadren amb el
vídeo (Fase 0: desplaçaments de 0,9-2,5 s i LRC de versions diferents).
"""

from __future__ import annotations

import logging
import re
import time
from difflib import SequenceMatcher

import requests

from .. import __version__

log = logging.getLogger(__name__)

URL_LRCLIB = "https://lrclib.net/api/search"
_RE_TEMPS_LRC = re.compile(r"^\s*\[\d+:\d+(?:\.\d+)?\]\s*")
_RE_TAGS = re.compile(r"<ch>[^<]*</ch>")


def text_de_content(content: str) -> str:
    """Treu acords i seccions d'un `content` del canconer (per fer servir la lletra de la BD)."""
    linies = []
    for l in content.split("\n"):
        if l.strip().startswith("<sec>"):
            continue
        neta = re.sub(r"\s+", " ", _RE_TAGS.sub("", l)).strip()
        if neta:
            linies.append(neta)
    return "\n".join(linies)


def _similitud(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _cerca(params: dict, intents: int = 6) -> list[dict]:
    capcalera = {"User-Agent": f"transcriptor/{__version__} (https://guitarreo.cat)"}
    for i in range(intents):
        try:
            r = requests.get(URL_LRCLIB, params=params, headers=capcalera, timeout=20)
        except requests.RequestException as e:
            log.warning("LRCLIB: %s", e)
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (429, 500, 502, 503, 504):
                log.warning("LRCLIB respon %s", r.status_code)
                return []
        time.sleep(5 * (i + 1))  # el servidor respon 503 sovint quan està saturat
    return []


def lrclib(titol: str, artista: str, durada: float) -> str | None:
    """Text (amb salts de línia) de la millor coincidència de LRCLIB, o None."""
    if not titol:
        return None
    resultats = _cerca({"track_name": titol, "artist_name": artista}) if artista else []
    if not resultats:
        resultats = _cerca({"q": f"{titol} {artista}".strip()})
    millor, puntuacio = None, 0.0
    for r in resultats:
        if r.get("instrumental") or not (r.get("plainLyrics") or r.get("syncedLyrics")):
            continue
        p = _similitud(titol, r.get("trackName", "")) + 0.5 * _similitud(artista, r.get("artistName", ""))
        if r.get("duration") and durada:
            p -= min(abs(r["duration"] - durada) / 30, 1.0)  # penalitza durades molt diferents
        if p > puntuacio:
            millor, puntuacio = r, p
    if millor is None or puntuacio < 0.8:
        return None
    if millor.get("plainLyrics"):
        return millor["plainLyrics"].strip()
    return "\n".join(_RE_TEMPS_LRC.sub("", l) for l in millor["syncedLyrics"].splitlines()).strip()


def obte(text_usuari: str | None, content_bd: str | None, titol: str, artista: str, durada: float,
         usar_lrclib: bool = True) -> tuple[str | None, str]:
    """Retorna (text, font) amb font a user|db|lrclib|whisper."""
    if text_usuari and text_usuari.strip():
        return text_usuari.strip(), "user"
    if content_bd:
        text = text_de_content(content_bd)
        if text:
            return text, "db"
    if usar_lrclib:
        text = lrclib(titol, artista, durada)
        if text:
            return text, "lrclib"
    return None, "whisper"
