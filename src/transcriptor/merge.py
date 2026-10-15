"""Fusió: acords + paraules + línies → seqüència d'elements per al render i l'estructura.

Elements (en ordre temporal):
- {"tipus": "linia", "start", "end", "word_range", "text", "acords": [[posició, etiqueta, t], ...]}
- {"tipus": "instrumental", "start", "end", "acords": [[etiqueta, t], ...]}

Regles de col·locació:
- Un acord pertany a la línia si cau entre l'inici de la línia (menys mitja pulsació de tolerància)
  i l'inici de la següent, sempre que no sigui en un tram llarg sense veu (llavors és instrumental).
- Dins la línia, va a la paraula que sona en aquell moment, a la lletra proporcional al temps
  (com fa la BD: "Sis<ch>E</ch>et"). Si cau en una pausa entre paraules, a l'inici de la següent.
- Si una línia comença amb un acord que ja sonava (sense canvi just a l'inici), es repeteix a la
  posició 0 perquè cada línia es pugui llegir sola, com a la BD.
"""

from __future__ import annotations

import bisect

import numpy as np

COMPASSOS_MIN_INSTRUMENTAL = 1.5  # un buit sense veu més llarg que això és instrumental
MARGE_REPETICIO_INICI = 2  # lletres: un canvi d'acord tan a prop de l'inici es mou a la posició 0
PENALITZACIO_POSTERIOR = 1.5  # cost relatiu de posar l'acord en una paraula que comença després del canvi


def _durada_compas(beats: list[dict]) -> float:
    if len(beats) < 2:
        return 2.0
    ibi = float(np.median(np.diff([b["t"] for b in beats])))
    per_compas = max(b["beat"] for b in beats)
    return ibi * per_compas


def _posicio(paraules: list[dict], rang: tuple[int, int], t: float, tol: float) -> int:
    """Posició de caràcter dins el text de la línia (paraules unides amb un espai).

    Tria la paraula amb l'inici més proper al canvi d'acord. Les paraules que comencen després del
    canvi es penalitzen (PENALITZACIO_POSTERIOR): a la BD, l'acord sol anar a la paraula que ja ha
    començat quan l'acord canvia (benchmark: Δ mediana +0,12 s, amb cua fins a +0,75 s).
    """
    inici, fi = rang
    ultima = paraules[fi - 1]
    if t >= ultima["end"] + tol:
        return sum(len(paraules[k]["text"]) + 1 for k in range(inici, fi))  # després de la lletra
    offsets, offset = [], 0
    for k in range(inici, fi):
        offsets.append(offset)
        offset += len(paraules[k]["text"]) + 1

    def cost(k: int) -> float:
        d = t - paraules[k]["start"]
        return d if d >= 0 else -d * PENALITZACIO_POSTERIOR

    k = min(range(inici, fi), key=cost)
    w = paraules[k]
    durada = max(w["end"] - w["start"], 1e-3)
    frac = min(max((t - w["start"]) / durada, 0.0), 0.999)
    return offsets[k - inici] + int(frac * len(w["text"]))


def colloca(paraules: list[dict], rangs: list[list[int]], acords: list[dict], beats: list[dict],
            durada: float) -> list[dict]:
    compas = _durada_compas(beats)
    ibi = compas / max((max(b["beat"] for b in beats) if beats else 4), 1)
    tol = ibi / 2

    linies = []
    for a, b in rangs:
        if b <= a:
            continue
        linies.append({
            "tipus": "linia", "start": paraules[a]["start"], "end": paraules[b - 1]["end"],
            "word_range": [a, b], "text": " ".join(paraules[k]["text"] for k in range(a, b)),
            "acords": [],
        })

    elements: list[dict] = []
    inicis = [l["start"] for l in linies]
    instrumental: dict | None = None
    for ac in acords:
        t = ac["start"]
        k = bisect.bisect_right(inicis, t + tol) - 1  # última línia que ha començat
        if k >= 0:
            linia = linies[k]
            seguent = inicis[k + 1] if k + 1 < len(linies) else float("inf")
            # Dins la línia, o just després si el buit fins a la següent és curt
            buit_curt = (seguent - linia["end"]) < compas * COMPASSOS_MIN_INSTRUMENTAL
            if t <= linia["end"] + tol or (buit_curt and t < seguent - tol):
                linia["acords"].append([_posicio(paraules, linia["word_range"], t, tol), ac["label"], t])
                instrumental = None
                continue
        # Tram sense veu: acords en una zona instrumental (abans de la línia k+1)
        if instrumental is None or instrumental["_abans_de"] != k + 1:
            instrumental = {"tipus": "instrumental", "start": t, "end": ac["end"], "acords": [],
                            "_abans_de": k + 1}
            elements.append(instrumental)
        instrumental["acords"].append([ac["label"], t])
        instrumental["end"] = ac["end"]

    # Repeteix a l'inici de línia l'acord que ja sonava
    for linia in linies:
        # Si ja hi ha un canvi a les primeres lletres, repetir l'anterior només fa soroll
        if linia["acords"] and linia["acords"][0][0] <= MARGE_REPETICIO_INICI:
            linia["acords"][0][0] = 0
            continue
        sonant = [ac for ac in acords if ac["start"] < linia["start"] - tol < ac["end"]
                  or ac["start"] <= linia["start"] < ac["end"]]
        if sonant:
            linia["acords"].insert(0, [0, sonant[-1]["label"], linia["start"]])

    # Posicions estrictament creixents (dos acords no poden compartir lletra)
    for linia in linies:
        ultima = -1
        for ac in linia["acords"]:
            ac[0] = max(ac[0], ultima + 1)
            ultima = ac[0]

    # Intercala les zones instrumentals entre les línies
    resultat: list[dict] = []
    per_posicio: dict[int, list[dict]] = {}
    for z in elements:
        per_posicio.setdefault(z.pop("_abans_de"), []).append(z)
    for k, linia in enumerate(linies):
        resultat.extend(per_posicio.get(k, []))
        resultat.append(linia)
    resultat.extend(per_posicio.get(len(linies), []))
    return resultat
