"""Seccions quadrades amb el compàs (després de structure.detecta, abans del render).

`structure.detecta` decideix quines línies van juntes i com es diu cada secció, però les fronteres
surten dels temps de la veu: comencen a qualsevol temps i entre seccions hi ha forats i solapaments.
El mode arranjament del canconer pot canviar l'ordre de les seccions i, per sonar continu, cada
salt ha de passar del final d'un compàs a l'inici d'un altre. Aquí:

1. Cada secció comença en un inici de compàs. Instrumental: el compàs del primer acord. Amb lletra:
   el primer compàs que comença amb la veu; si la veu entra a la segona meitat del compàs anterior
   és una anacrusi, que no compta per a la llargada (però el text continua a la seva línia).
2. Les seccions són contigües: cadascuna acaba on comença la següent.
3. Llargades rodones (prior suau): les fronteres es poden moure fins a MAX_MOURE compassos dins
   dels trams sense veu, i una programació dinàmica prefereix llargades múltiples de 4 (o de 2) i
   iguals a les de les altres seccions amb el mateix nom. Si la lletra diu 6 compassos, en són 6.
4. Les seccions de menys de MIN_COMPASSOS són errors: s'uneixen a l'anterior.
5. Les zones instrumentals es parteixen per les fronteres, i els acords de després d'una línia que
   cauen a la secció següent hi passen com a entrada instrumental.
6. Després del títol de secció sempre hi ha l'acord amb què comença, encara que ja sonés
   (merge.colloca no repeteix l'acord que sonava, però una secció pot venir d'una altra).
"""

from __future__ import annotations

import bisect
from collections import Counter

import numpy as np

from .. import merge

MIN_COMPASSOS = 2
MAX_MOURE = 2
COST_MOURE = 0.75  # per compàs que es mou una frontera
BO_CANVI = 0.5  # la frontera cau en un canvi d'acord
COST_PARELL = 1.0  # llargada parella però no múltiple de 4
COST_SENAR = 2.0
BO_MATEIXA_LLARGADA = 1.0  # la mateixa llargada que la majoria de seccions amb el mateix nom
REPETIBLES = ("Estrofa", "Tornada", "Pre-tornada")


def _cost_llargada(n: int, moda: int | None) -> float:
    cost = 0.0 if n % 4 == 0 else COST_PARELL if n % 2 == 0 else COST_SENAR
    return cost - (BO_MATEIXA_LLARGADA if moda == n else 0.0)


def _primer_acord(e: dict) -> float:
    return e["acords"][0][1] if e["acords"] else e["start"]


def _candidata(s: dict, elements: list[dict], terres: list[float], tol: float, mig: float) -> int:
    """Índex (a `terres`) del compàs on comença la secció."""
    e = elements[s["elements"][0]]
    if e["tipus"] == "instrumental":
        return max(bisect.bisect_right(terres, _primer_acord(e) + tol) - 1, 0)
    k = min(bisect.bisect_left(terres, e["start"] - tol), len(terres) - 1)
    if terres[k] - e["start"] > mig:  # la veu ha entrat tard dins del compàs anterior
        k -= 1
    return max(k, 0)


def _fi_lletra(s: dict, elements: list[dict]) -> float | None:
    linies = [elements[i] for i in s["elements"] if elements[i]["tipus"] == "linia"]
    return max(l["end"] for l in linies) if linies else None


def _uneix_curtes(seccions: list[dict], cands: list[int], fi_idx: int,
                  elements: list[dict]) -> tuple[list[dict], list[int]]:
    def te_lletra(s: dict) -> bool:
        return any(elements[i]["tipus"] == "linia" for i in s["elements"])

    while len(seccions) > 1:
        llargs = [b - a for a, b in zip(cands, cands[1:] + [fi_idx])]
        i = next((i for i, n in enumerate(llargs) if n < MIN_COMPASSOS), None)
        if i is None:
            break
        desti = i - 1 if i > 0 else 1
        if te_lletra(seccions[i]) and not te_lletra(seccions[desti]):
            # Una secció amb lletra no pot quedar dins d'un instrumental: mana el nom de la de lletra
            seccions[desti]["label"] = seccions[i]["label"]
        seccions[desti]["elements"] = sorted(seccions[desti]["elements"] + seccions[i]["elements"])
        if desti > i:
            cands[desti] = min(cands[desti], cands[i])
        del seccions[i], cands[i]
    # Dues seccions seguides del mateix tipus no repetible (dos instrumentals) en són una
    i = 1
    while i < len(seccions):
        if seccions[i]["label"] == seccions[i - 1]["label"] and seccions[i]["label"] not in REPETIBLES:
            seccions[i - 1]["elements"] = sorted(seccions[i - 1]["elements"] + seccions[i]["elements"])
            del seccions[i], cands[i]
        else:
            i += 1
    return seccions, cands


def _fronteres(opcions: list[list[int]], cands: list[int], canvis: set[int], etiquetes: list[str],
               fi_idx: int, moda: dict[str, int]) -> list[int] | None:
    """Programació dinàmica: una frontera per secció (la primera, fixa) amb el cost mínim."""
    def cost_pos(i: int, j: int) -> float:
        return COST_MOURE * abs(j - cands[i]) - (BO_CANVI if j in canvis else 0.0)

    millor = {opcions[0][0]: (0.0, None)}
    rastre = [millor]
    for i in range(1, len(opcions)):
        actual = {}
        for j in opcions[i]:
            candidats = [(c + _cost_llargada(j - jp, moda.get(etiquetes[i - 1])) + cost_pos(i, j), jp)
                         for jp, (c, _) in rastre[-1].items() if j - jp >= MIN_COMPASSOS]
            if candidats:
                actual[j] = min(candidats)
        if not actual:
            return None
        rastre.append(actual)
    finals = [(c + _cost_llargada(fi_idx - j, moda.get(etiquetes[-1])), j) for j, (c, _) in rastre[-1].items()
              if fi_idx - j >= 1]
    if not finals:
        return None
    j = min(finals)[1]
    resultat = [j]
    for capa in reversed(rastre[1:]):
        j = capa[j][1]
        resultat.append(j)
    return resultat[::-1]


def _talla(e: dict, inici: float, fi: float, sonant) -> dict | None:
    """Tros [inici, fi) d'una zona instrumental; el primer temps sempre porta l'acord que hi sona."""
    acords = [a for a in e["acords"] if inici <= a[1] < fi]
    puls = [list(p) for p in e.get("pulsacions", []) if inici <= p[0] < fi]
    if not acords and not puls:
        return None
    t0 = min([a[1] for a in acords] + [p[0] for p in puls])
    if puls and puls[0][2] is None:
        puls[0][2] = sonant(puls[0][0])
    if not acords or acords[0][1] > t0:
        etiqueta = puls[0][2] if puls else sonant(t0)
        if etiqueta:
            acords.insert(0, [etiqueta, t0])
    if not acords:
        return None
    return {**e, "start": t0, "end": min(e["end"], fi), "acords": acords, "pulsacions": puls}


def quadra(elements: list[dict], seccions: list[dict], beats: list[dict], acords: list[dict],
           durada: float) -> tuple[list[dict], list[dict]]:
    """Retorna (elements, seccions) nous amb les seccions quadrades. `acords`: segments d'acord."""
    terres = [b["t"] for b in beats if b["beat"] == 1]
    if len(terres) < 2 or not seccions:
        return elements, seccions
    compas = float(np.median(np.diff(terres)))
    # On Beat This! no ha trobat pulsacions (parlat, silencis) no hi ha compassos: l'inici de cada
    # element del forat fa de frontera possible, sense quadrar
    terres = sorted(terres + [e["start"] for e in elements
                              if min(abs(t - e["start"]) for t in terres) > compas])
    tol = merge._durada_compas(beats) / max(max(b["beat"] for b in beats), 1) / 2
    inicis_acords = [a["start"] for a in acords]

    def sonant(t: float) -> str | None:
        k = bisect.bisect_right(inicis_acords, t + tol) - 1
        return acords[k]["label"] if k >= 0 else None

    seccions = [dict(s, elements=list(s["elements"])) for s in seccions]
    t_fi = max(e["end"] for e in elements)
    fi_idx = bisect.bisect_left(terres, t_fi - tol)
    cands = [_candidata(s, elements, terres, tol, compas / 2) for s in seccions]
    seccions, cands = _uneix_curtes(seccions, cands, fi_idx, elements)

    # Opcions de cada frontera: sense travessar la lletra de la secció anterior ni la pròpia
    opcions = [[cands[0]]]
    for i in range(1, len(seccions)):
        fi_ant = _fi_lletra(seccions[i - 1], elements)
        baix = cands[i] - MAX_MOURE
        if fi_ant is not None:
            baix = max(baix, bisect.bisect_left(terres, fi_ant - tol))
        te_lletra_a_l_inici = elements[seccions[i]["elements"][0]]["tipus"] == "linia"
        alt = cands[i] if te_lletra_a_l_inici else cands[i] + MAX_MOURE
        opcions.append(list(range(min(baix, cands[i]), alt + 1)))
    canvis = set()
    for a in acords:
        k = min(bisect.bisect_left(terres, a["start"] - tol), len(terres) - 1)
        if abs(terres[k] - a["start"]) <= tol:
            canvis.add(k)
    etiquetes = [s["label"] for s in seccions]
    fronteres = _fronteres(opcions, cands, canvis, etiquetes, fi_idx, {})
    if fronteres is not None:
        llargs = Counter()
        for i, et in enumerate(etiquetes):
            fi = fronteres[i + 1] if i + 1 < len(fronteres) else fi_idx
            llargs[(et, fi - fronteres[i])] += 1
        moda = {}
        for et in set(etiquetes):
            n, vegades = max(((n, v) for (e, n), v in llargs.items() if e == et), key=lambda x: x[1])
            if vegades >= 2:
                moda[et] = n
        fronteres = _fronteres(opcions, cands, canvis, etiquetes, fi_idx, moda) or fronteres
    if fronteres is None or any(b <= a for a, b in zip(fronteres, fronteres[1:])):
        fronteres = cands
    inicis = [terres[j] for j in fronteres]
    final = terres[fi_idx] if fi_idx < len(terres) else durada
    fins = inicis[1:] + [final]

    # Repartiment dels elements per les fronteres noves
    per_seccio: list[list[dict]] = [[] for _ in seccions]
    entrades: list[list[list]] = [[] for _ in seccions]  # acords de cua que passen a la secció següent
    for si, s in enumerate(seccions):
        for i in s["elements"]:
            e = elements[i]
            if e["tipus"] == "linia":
                seguent = inicis[si + 1] if si + 1 < len(seccions) else None
                cua = [a for a in e["acords"] if seguent is not None and a[2] >= seguent - tol
                       and a[0] >= len(e["text"])]
                if cua:
                    entrades[si + 1].extend([a[1], a[2]] for a in cua)
                    e = {**e, "acords": [a for a in e["acords"] if a not in cua]}
                per_seccio[si].append(e)
                continue
            for k in range(len(seccions)):
                tros = _talla(e, inicis[k] if k else -np.inf, fins[k] if k + 1 < len(seccions) else np.inf, sonant)
                if tros:
                    per_seccio[k].append(tros)

    for si in range(1, len(seccions)):
        primer = min(per_seccio[si], key=lambda e: e["start"], default=None)
        if primer and primer["tipus"] == "instrumental" and primer["start"] <= inicis[si] + tol:
            continue
        if primer and primer["start"] - inicis[si] <= compas - tol:
            # La veu entra dins del primer compàs: l'acord de la frontera va a l'inici de la línia
            if entrades[si] and primer["tipus"] == "linia":
                k = per_seccio[si].index(primer)
                per_seccio[si][k] = {**primer, "acords": [[0, entrades[si][-1][0], entrades[si][-1][1]]]
                                     + [a for a in primer["acords"] if a[0] > 0]}
            continue
        # Compassos sense veu a l'inici de la secció: entrada instrumental des de la frontera
        ac = entrades[si]
        if not ac or ac[0][1] > inicis[si] + tol:
            ac = [[sonant(inicis[si]), inicis[si]]] + ac
        ac = [a for a in ac if a[0]]
        if ac:
            fi = primer["start"] if primer else fins[si]
            per_seccio[si].append({"tipus": "instrumental", "start": inicis[si], "end": fi, "acords": ac,
                                   "pulsacions": merge._pulsacions(ac, beats, fi, tol)})

    # Acord a l'inici de cada secció amb lletra (si no n'hi ha cap abans del primer compàs)
    for si, elems in enumerate(per_seccio):
        elems.sort(key=lambda e: e["start"])
        # Menys d'un compàs abans que entri la veu: l'acord va a l'inici de la línia (com quan l'acord
        # era a la cua de la línia anterior), tret que la línia ja hi tingui un canvi d'acord
        if (len(elems) > 1 and elems[0]["tipus"] == "instrumental" and elems[1]["tipus"] == "linia"
                and elems[1]["start"] - elems[0]["start"] < compas - tol
                and not any(a[0] <= merge.MARGE_REPETICIO_INICI for a in elems[1]["acords"])):
            zona = elems.pop(0)
            elems[0] = {**elems[0], "acords": [[0, zona["acords"][-1][0], zona["start"]]] + elems[0]["acords"]}
        if not elems or elems[0]["tipus"] != "linia":
            continue
        l = elems[0]
        if not any(a[2] <= inicis[si] + tol for a in l["acords"]) and (et := sonant(max(inicis[si], l["start"]))):
            l = elems[0] = {**l, "acords": [[0, et, l["start"]]] + [a for a in l["acords"] if a[0] > 0]}

    nous_elements: list[dict] = []
    noves: list[dict] = []
    n_estrofa = 0
    for si, s in enumerate(seccions):
        if not per_seccio[si]:
            if noves:
                noves[-1]["end"] = round(fins[si], 3)
            continue
        idx = list(range(len(nous_elements), len(nous_elements) + len(per_seccio[si])))
        nous_elements.extend(per_seccio[si])
        if s["label"] == "Estrofa":
            n_estrofa += 1
        noves.append({**s, "elements": idx, "start": round(inicis[si], 3), "end": round(fins[si], 3),
                      "name": f"Estrofa {n_estrofa}" if s["label"] == "Estrofa" else s["label"]})
    return nous_elements, noves
