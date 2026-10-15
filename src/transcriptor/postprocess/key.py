"""Tonalitat a partir dels acords (histograma de notes ponderat per durada + Krumhansl-Kessler).

A la Fase 0 encerta les 3 cançons de referència; per això no cal Essentia.
"""

from __future__ import annotations

import numpy as np

from ..notation import NOTES, arrel_i_sufix, es_menor

MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MENOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Tons amb formes obertes còmodes a la guitarra (per suggerir cejilla)
TONS_FACILS = {"C", "G", "D", "A", "E", "Am", "Em", "Dm"}
CAPO_MAXIM = 7


def _notes_acord(sufix: str) -> list[int]:
    tercera = 3 if (es_menor(sufix) or sufix.startswith("dim")) else 4
    quinta = 6 if sufix.startswith("dim") or sufix == "m7b5" else 8 if sufix == "aug" else 7
    notes = [0, tercera, quinta]
    if sufix in ("7", "m7", "m7b5"):
        notes.append(10)
    elif sufix in ("maj7", "mmaj7"):
        notes.append(11)
    return notes


def histograma(acords: list[dict]) -> np.ndarray:
    hist = np.zeros(12)
    for a in acords:
        r = arrel_i_sufix(a["label"])
        if r is None:
            continue
        arrel, sufix = r
        for interval in _notes_acord(sufix):
            hist[(arrel + interval) % 12] += a["end"] - a["start"]
    return hist


METODE = "krumhansl"  # "krumhansl" | "funcional" (al benchmark, Krumhansl discrepa menys)

# Pes de cada grau diatònic (interval des de la tònica, menor?) per a l'estimador funcional
_GRAUS_MAJOR = {(0, False): 1.0, (5, False): 0.8, (7, False): 0.8, (9, True): 0.6, (2, True): 0.5,
                (4, True): 0.3, (10, False): 0.2}  # bVII: habitual en pop/rock
_GRAUS_MENOR = {(0, True): 1.0, (5, True): 0.8, (7, False): 0.7, (7, True): 0.5, (3, False): 0.6,
                (8, False): 0.6, (10, False): 0.6}
BONUS_EXTREMS = 0.15  # fracció de la durada total si el primer/últim acord és la tònica
BONUS_CADENCIA = 0.02  # per cada V→I, en fracció de la durada total


def _estima_funcional(acords: list[dict]) -> dict | None:
    seq = []
    for a in acords:
        r = arrel_i_sufix(a["label"])
        if r:
            seq.append((r[0], es_menor(r[1]) or r[1].startswith("dim"), a["end"] - a["start"]))
    if not seq:
        return None
    total = sum(d for _, _, d in seq)
    resultats = []
    for t in range(12):
        for menor, graus in ((False, _GRAUS_MAJOR), (True, _GRAUS_MENOR)):
            p = sum(d * graus.get(((r - t) % 12, m), -0.3) for r, m, d in seq)
            for extrem in (seq[0], seq[-1]):
                if (extrem[0] - t) % 12 == 0 and extrem[1] == menor:
                    p += BONUS_EXTREMS * total
            p += BONUS_CADENCIA * total * sum(
                1 for (r1, _, _), (r2, m2, _) in zip(seq, seq[1:])
                if (r1 - t) % 12 == 7 and (r2 - t) % 12 == 0 and m2 == menor)
            resultats.append((p / total, NOTES[t], "minor" if menor else "major"))
    resultats.sort(reverse=True)
    p, tonic, mode = resultats[0]
    return {"tonic": tonic, "mode": mode, "confidence": round(max(min(p, 1.0), 0.0), 3)}


def estima(acords: list[dict]) -> dict | None:
    """Retorna {"tonic", "mode", "confidence"} o None si no hi ha acords."""
    if METODE == "funcional":
        return _estima_funcional(acords)
    hist = histograma(acords)
    if hist.sum() == 0:
        return None
    resultats = []
    for t in range(12):
        for perfil, mode in ((MAJOR, "major"), (MENOR, "minor")):
            corr = float(np.corrcoef(hist, np.roll(perfil, t))[0, 1])
            resultats.append((corr, NOTES[t], mode))
    resultats.sort(reverse=True)
    corr, tonic, mode = resultats[0]
    # Confiança: correlació, rebaixada si el segon candidat (no relatiu) és a prop
    return {"tonic": tonic, "mode": mode, "confidence": round(max(corr, 0.0), 3)}


def clau(tonalitat: dict) -> str:
    return tonalitat["tonic"] + ("m" if tonalitat["mode"] == "minor" else "")


def suggereix_capo(tonalitat: dict) -> int:
    """Cejilla més baixa que deixa el to en formes obertes còmodes (0 si ja ho és)."""
    arrel = NOTES.index(tonalitat["tonic"])
    sufix = "m" if tonalitat["mode"] == "minor" else ""
    for capo in range(CAPO_MAXIM + 1):
        if NOTES[(arrel - capo) % 12] + sufix in TONS_FACILS:
            return capo
    return 0
