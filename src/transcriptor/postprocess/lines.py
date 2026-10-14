"""Tall de línies quan la lletra ve només de l'ASR (sense text de referència).

Es talla per pauses llargues, per final de segment de Whisper amb pausa, o per longitud màxima.
Quan es talla per longitud, es prefereix la paraula que comença més a prop d'un inici de compàs.
"""

from __future__ import annotations

import bisect


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
        buit = paraules[i]["start"] - paraules[i - 1]["end"]
        fi_seg = round(paraules[i - 1]["end"], 2) in fins_segment and buit > pausa / 3
        if buit > pausa or fi_seg:
            linies.append([inici, i])
            inici = i
        elif i - inici >= max_paraules:
            tall = _millor_tall(paraules, inici, i, inicis_compas)
            linies.append([inici, tall])
            inici = tall
    return linies


def _millor_tall(paraules: list[dict], inici: int, fi: int, inicis_compas: list[float]) -> int:
    """Entre la meitat i el final de la línia, la paraula més propera a un inici de compàs."""
    millor, distancia = fi, float("inf")
    for k in range(inici + max(2, (fi - inici) // 2), fi + 1):
        t = paraules[k]["start"]
        j = bisect.bisect_left(inicis_compas, t)
        d = min((abs(inicis_compas[x] - t) for x in (j - 1, j) if 0 <= x < len(inicis_compas)),
                default=float("inf"))
        if d < distancia:
            millor, distancia = k, d
    return millor
