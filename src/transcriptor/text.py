"""Utilitats de text: normalització i tokenització de lletres."""

from __future__ import annotations

import re
import unicodedata

_RE_SUBPARAULA = re.compile(r"[\w·]+")


def normalitza(text: str) -> list[str]:
    """Subparaules en minúscula sense puntuació. "L'avi" → ["l", "avi"]; conserva accents i l·l."""
    text = unicodedata.normalize("NFC", text.lower()).replace("’", "'").replace("l.l", "l·l")
    return _RE_SUBPARAULA.findall(text)


def lletres(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalpha())


def linies_de_text(text: str) -> list[list[str]]:
    """Text de lletra → línies de paraules visibles (tal com s'han d'escriure). Salta línies buides."""
    sortida = []
    for linia in text.replace("\r", "").split("\n"):
        paraules = linia.split()
        if paraules and lletres(linia):
            sortida.append(paraules)
    return sortida


def wer(referencia: list[str], hipotesi: list[str]) -> float:
    """Word error rate per distància d'edició a nivell de paraula."""
    anterior = list(range(len(hipotesi) + 1))
    for i, r in enumerate(referencia, 1):
        actual = [i] + [0] * len(hipotesi)
        for j, h in enumerate(hipotesi, 1):
            actual[j] = min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (r != h))
        anterior = actual
    return anterior[-1] / max(len(referencia), 1)
