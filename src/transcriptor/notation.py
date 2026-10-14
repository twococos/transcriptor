"""Notació d'acords del projecte: anglesa amb sostinguts i sufixos de CHORD_MODIFIERS.

Còpia de constants del canconer (només lectura):
- src/lib/transpose.ts → CHROMATIC
- src/lib/editor/chordFunctions.ts → CHORD_MODIFIERS
"""

from __future__ import annotations

import re

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BEMOLLS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E",
           "E#": "F", "B#": "C"}
CHORD_MODIFIERS = ["maj7", "7", "m7", "sus2", "sus4", "add9", "6", "dim", "m7b5", "mmaj7", "9", "13", "aug"]

# Qualitat de BTC (Harte) → sufix del projecte per nivell de vocabulari
_SUFIX = {
    #            majmin  sevenths  full
    "maj":      ("",     "",       ""),
    "min":      ("m",    "m",      "m"),
    "7":        ("",     "7",      "7"),
    "maj7":     ("",     "maj7",   "maj7"),
    "min7":     ("m",    "m7",     "m7"),
    "maj6":     ("",     "",       "6"),
    "min6":     ("m",    "m",      "m6"),
    "minmaj7":  ("m",    "m",      "mmaj7"),
    "dim":      ("m",    "dim",    "dim"),
    "dim7":     ("m",    "dim",    "dim"),
    "hdim7":    ("m",    "m7b5",   "m7b5"),
    "aug":      ("",     "",       "aug"),
    "sus2":     ("",     "",       "sus2"),
    "sus4":     ("",     "",       "sus4"),
}
NIVELLS = {"majmin": 0, "sevenths": 1, "full": 2}

_RE_ACORD = re.compile(r"^([A-G][#b]?)(.*)$")


def nota(n: str) -> str:
    """Normalitza una nota a sostinguts."""
    return BEMOLLS.get(n, n)


def de_harte(etiqueta: str, nivell: str = "sevenths") -> str | None:
    """'F#:min7' → 'F#m7' (segons el nivell). None per a 'N' / 'X'."""
    if etiqueta in ("N", "X"):
        return None
    arrel, _, qualitat = etiqueta.partition(":")
    qualitat = qualitat.split("/")[0] or "maj"
    sufix = _SUFIX.get(qualitat, ("", "", ""))[NIVELLS[nivell]]
    return nota(arrel) + sufix


def arrel_i_sufix(acord: str) -> tuple[int, str] | None:
    """'F#m7' → (6, 'm7'). Ignora el baix ('/E'). None si no és un acord."""
    m = _RE_ACORD.match(acord.strip())
    if not m:
        return None
    return NOTES.index(nota(m.group(1))), m.group(2).split("/")[0]


def es_menor(sufix: str) -> bool:
    return sufix.startswith("m") and not sufix.startswith("maj")


def majmin(acord: str) -> tuple[int, str] | None:
    """Acord → (arrel, 'maj'|'min'), per comparar a nivell majmin."""
    r = arrel_i_sufix(acord)
    if r is None:
        return None
    arrel, sufix = r
    return arrel, "min" if (es_menor(sufix) or sufix.startswith("dim")) else "maj"


def transposa(acord: str, semitons: int) -> str:
    r = _RE_ACORD.match(acord.strip())
    if not r:
        return acord
    arrel = NOTES[(NOTES.index(nota(r.group(1))) + semitons) % 12]
    resta = r.group(2)
    if "/" in resta:
        cos, baix = resta.split("/", 1)
        mb = _RE_ACORD.match(baix)
        if mb:
            baix = NOTES[(NOTES.index(nota(mb.group(1))) + semitons) % 12] + mb.group(2)
        resta = f"{cos}/{baix}"
    return arrel + resta
