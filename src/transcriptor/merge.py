"""Fusió: acords + paraules + línies → seqüència d'elements per al render i l'estructura.

Elements (en ordre temporal):
- {"tipus": "linia", "start", "end", "word_range", "text", "acords": [[posició, etiqueta, t], ...]}
- {"tipus": "instrumental", "start", "end", "acords": [[etiqueta, t], ...],
   "pulsacions": [[t, temps del compàs, etiqueta o None], ...]}  (per dibuixar-ne els compassos)

Regles de col·locació:
- Un acord pertany a la línia si cau entre l'inici de la línia (menys mitja pulsació de tolerància)
  i l'inici de la següent, sempre que no sigui en un tram llarg sense veu (llavors és instrumental).
- Dins la línia, va a la paraula que sona en aquell moment, a la lletra proporcional al temps
  (com fa la BD: "Sis<ch>E</ch>et"). Si cau en una pausa entre paraules, a l'inici de la següent.
- L'acord que ja sonava a l'inici d'una línia no es repeteix: s'entén que dura fins al següent.
  (La BD sí que el repeteix, però amb anacrusi surt l'acord anterior a l'inici de cada línia i
  l'acord nou dues lletres més enllà, cosa que confon.)
"""

from __future__ import annotations

import bisect

import numpy as np

COMPASSOS_MIN_INSTRUMENTAL = 1.5  # un buit sense veu més llarg que això és instrumental
MARGE_REPETICIO_INICI = 2  # lletres: un canvi d'acord tan a prop de l'inici es mou a la posició 0
PENALITZACIO_POSTERIOR = 2.5  # cost relatiu de posar l'acord en una paraula que comença després del canvi
AVANC_ACORD_S = 0.1  # s: es tria la paraula com si l'acord canviés aquest temps abans
COMPASSOS_FINAL = 1  # compassos que es mostren a partir de l'últim acord d'un instrumental sense lletra després


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

    t = t - AVANC_ACORD_S
    k = min(range(inici, fi), key=cost)
    w = paraules[k]
    durada = max(w["end"] - w["start"], 1e-3)
    frac = min(max((t - w["start"]) / durada, 0.0), 0.999)
    return offsets[k - inici] + int(frac * len(w["text"]))


def _pulsacions(acords: list[list], beats: list[dict], fi: float, tol: float) -> list[list]:
    """Pulsacions des del primer acord de la zona fins a `fi`, amb l'acord que hi comença (o None).

    Cada acord va a la pulsació més propera (els acords ja es calculen per pulsació).
    """
    ts = [b["t"] for b in beats]
    if not ts:
        return []

    def propera(t: float) -> int:
        k = bisect.bisect_left(ts, t)
        return min((j for j in (k - 1, k) if 0 <= j < len(ts)), key=lambda j: abs(ts[j] - t))

    etiquetes = {propera(t): et for et, t in acords}
    inici = min(etiquetes)
    fi_idx = max(bisect.bisect_left(ts, fi - tol), max(etiquetes) + 1)
    return [[ts[j], beats[j]["beat"], etiquetes.get(j)] for j in range(inici, fi_idx)]


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

    # Un canvi a les primeres lletres va a l'inici de la línia. Un "canvi" al mateix acord que ja
    # sonava no s'escriu.
    anterior = None
    for linia in sorted(linies + elements, key=lambda e: e["start"]):
        if linia["tipus"] != "linia":
            anterior = linia["acords"][-1][0]
            continue
        linia["acords"] = [ac for ac, prev in zip(linia["acords"], [[None, anterior]] + linia["acords"])
                           if ac[1] != prev[1]]
        if linia["acords"]:
            anterior = linia["acords"][-1][1]
        if linia["acords"] and linia["acords"][0][0] <= MARGE_REPETICIO_INICI:
            linia["acords"][0][0] = 0

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
        k = z.pop("_abans_de")
        fi = inicis[k] if k < len(linies) else min(z["end"], z["acords"][-1][1] + compas * COMPASSOS_FINAL)
        z["pulsacions"] = _pulsacions(z["acords"], beats, fi, tol)
        per_posicio.setdefault(k, []).append(z)
    for k, linia in enumerate(linies):
        resultat.extend(per_posicio.get(k, []))
        resultat.append(linia)
    resultat.extend(per_posicio.get(len(linies), []))
    return resultat
