"""Paraules i tall de línies quan la lletra ve només de l'ASR (sense text de referència).

- `uneix_fragments`: Whisper parteix "L'avi" en "L" + "'avi" i "desfer-nos-en" en "desfer" + "-nos-en".
- `talla`: talla per pauses llargues, per final de segment de Whisper amb pausa, després de
  puntuació forta si la línia ja és prou llarga, o per longitud màxima (preferint la puntuació i,
  si no n'hi ha, la paraula més propera a un inici de compàs).
"""

from __future__ import annotations

import bisect

PUNTUACIO_FORTA = (".", "?", "!", ";", ":")
PUNTUACIO_FEBLE = (",",)
MIN_PARAULES_TALL_PUNTUACIO = 4


def uneix_fragments(paraules: list[dict]) -> list[dict]:
    """Ajunta fragments d'apòstrof i guió a la paraula veïna."""
    sortida: list[dict] = []
    for w in paraules:
        text = w["text"].strip()
        if not text:
            continue
        if sortida and (text[0] in "'’-" or sortida[-1]["text"].endswith(("'", "’", "-"))):
            anterior = sortida[-1]
            anterior["text"] += text
            anterior["end"] = w["end"]
            if anterior.get("conf") is not None and w.get("conf") is not None:
                anterior["conf"] = round(min(anterior["conf"], w["conf"]), 3)
            continue
        sortida.append({**w, "text": text})
    return sortida


def talla(paraules: list[dict], segments: list[dict], inicis_compas: list[float],
          pausa: float = 0.6, max_paraules: int = 10) -> list[list[int]]:
    """Retorna rangs [inici, fi) de paraules per línia."""
    if not paraules:
        return []
    fins_segment = {round(s["end"], 2) for s in segments}
    linies, inici = [], 0
    for i in range(1, len(paraules) + 1):
        if i == len(paraules):
            linies.append([inici, i])
            break
        anterior = paraules[i - 1]
        buit = paraules[i]["start"] - anterior["end"]
        fi_seg = round(anterior["end"], 2) in fins_segment and buit > pausa / 3
        puntuacio = anterior["text"].endswith(PUNTUACIO_FORTA) and i - inici >= MIN_PARAULES_TALL_PUNTUACIO
        if buit > pausa or fi_seg or puntuacio:
            linies.append([inici, i])
            inici = i
        elif i - inici >= max_paraules:
            tall = _millor_tall(paraules, inici, i, inicis_compas)
            linies.append([inici, tall])
            inici = tall
    return linies


def _millor_tall(paraules: list[dict], inici: int, fi: int, inicis_compas: list[float]) -> int:
    """Tall dins la segona meitat de la línia: després d'una coma si n'hi ha; si no, a la paraula
    més propera a un inici de compàs."""
    candidats = range(inici + max(2, (fi - inici) // 2), fi + 1)
    for k in reversed(candidats):
        if paraules[k - 1]["text"].endswith(PUNTUACIO_FEBLE + PUNTUACIO_FORTA):
            return k
    millor, distancia = fi, float("inf")
    for k in candidats:
        t = paraules[k]["start"]
        j = bisect.bisect_left(inicis_compas, t)
        d = min((abs(inicis_compas[x] - t) for x in (j - 1, j) if 0 <= x < len(inicis_compas)),
                default=float("inf"))
        if d < distancia:
            millor, distancia = k, d
    return millor
