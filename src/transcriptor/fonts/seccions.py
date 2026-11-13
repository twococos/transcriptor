"""Seccions contrastades amb les tabs: on comença cada secció i de quin tipus és.

Entra després de `structure.detecta` i abans de `postprocess/seccions.quadra` (que continua posant
les fronteres a terra). Amb l'aparellament de paraules de cada tab (alinea.py), cada línia de
l'anàlisi sap a quina secció de la tab correspon. Llavors:

- **Talls**: entre dues línies seguides hi ha frontera si ho diu més de la meitat del pes de les
  fonts que les cobreixen totes dues. `structure.detecta` vota com una font més (PES_DETECCIO).
  Les tabs sense marques de secció s'abstenen. Una zona instrumental sempre separa.
- **Noms**: el tipus més votat de cada tram (Estrofa, Tornada, Pont…).
- **Instrumentals**: el tipus de la secció de la tab (Intro, Solo, Interludi, Outro) que té els
  acords que hi cauen.
"""

from __future__ import annotations

from collections import Counter

from .alinea import Alineacio

PES_DETECCIO = 0.8
MIN_APARELLADES = 0.6  # una tab amb menys lletra aparellada no vota seccions
REPETIBLES = ("Instrumental", "Pont")


def _seccio_tab(al: Alineacio, e: dict) -> tuple[int, int] | None:
    """(secció de la tab, repetició) de la majoria de paraules d'una línia de l'anàlisi."""
    linies = [al.linia_paraula[w] for w in range(*e["word_range"]) if w in al.linia_paraula]
    if not linies:
        return None
    li = Counter(linies).most_common(1)[0][0]
    l = al.tab.linies[li]
    return (l.seccio, l.repeticio) if l.seccio is not None else None


def _vota_instrumental(al: Alineacio, e: dict, vores) -> str | None:
    """Tipus de la secció de la tab que té la majoria d'acords sense lletra dins la zona."""
    vots = Counter()
    for a in al.acords:
        t = vores[a.inici]
        l = al.tab.linies[a.linia]
        if e["start"] <= t < e["end"] and not l.text and l.seccio is not None:
            tipus = al.tab.seccions[l.seccio].tipus
            if tipus:
                vots[tipus] += vores[a.fi] - t
    return vots.most_common(1)[0][0] if vots else None


def corregeix(elements: list[dict], seccions: list[dict], fonts: list[tuple[Alineacio, float]],
              vores) -> tuple[list[dict], int]:
    """Retorna (seccions noves en el format de structure.detecta, línies que canvien de tipus o de tram)."""
    fonts = [(al, w) for al, w in fonts
             if al.aparellades >= MIN_APARELLADES and sum(s.tipus is not None for s in al.tab.seccions) >= 2]
    if not fonts:
        return seccions, 0
    seccio_de: dict[int, int] = {i: k for k, s in enumerate(seccions) for i in s["elements"]}
    linies = [i for i, e in enumerate(elements) if e["tipus"] == "linia"]
    per_font = [{i: _seccio_tab(al, elements[i]) for i in linies} for al, _ in fonts]

    # Talls entre línies consecutives
    talls: set[int] = set()  # índex de la línia que obre secció
    for a, b in zip(linies, linies[1:]):
        if any(elements[x]["tipus"] == "instrumental" for x in range(a + 1, b)):
            talls.add(b)
            continue
        si = PES_DETECCIO if seccio_de.get(a) != seccio_de.get(b) else 0.0
        total = PES_DETECCIO
        for (al, w), sec in zip(fonts, per_font):
            if sec[a] is None or sec[b] is None:
                continue
            total += w
            if sec[a] != sec[b]:
                si += w
        if si > total / 2:
            talls.add(b)
    if linies:
        talls.add(linies[0])

    # Trams de línies i el seu tipus
    trams: list[list[int]] = []
    for i in linies:
        if i in talls or not trams:
            trams.append([i])
        else:
            trams[-1].append(i)
    noves: list[dict] = []
    for tram in trams:
        vots = Counter()
        for i in tram:
            vots[seccions[seccio_de[i]]["label"]] += PES_DETECCIO
            for (al, w), sec in zip(fonts, per_font):
                if sec[i] is not None:
                    tipus = al.tab.seccions[sec[i][0]].tipus
                    if tipus and tipus not in ("Intro", "Outro"):  # una línia amb lletra no és una intro
                        vots[tipus] += w
        noves.append({"label": vots.most_common(1)[0][0], "elements": list(tram)})
    for i, e in enumerate(elements):
        if e["tipus"] != "instrumental":
            continue
        actual = seccions[seccio_de[i]]["label"] if i in seccio_de else "Instrumental"
        vots = Counter({actual: PES_DETECCIO})
        for al, w in fonts:
            t = _vota_instrumental(al, e, vores)
            if t:
                vots[t] += w
        etiqueta = vots.most_common(1)[0][0]
        if etiqueta in ("Estrofa", "Tornada", "Pre-tornada"):
            etiqueta = actual  # una zona sense veu no és una estrofa (els acords d'una entrada)
        noves.append({"label": etiqueta, "elements": [i]})
    noves.sort(key=lambda s: s["elements"][0])

    fusionades: list[dict] = []
    for s in noves:
        if fusionades and fusionades[-1]["label"] == s["label"] and s["label"] in REPETIBLES:
            fusionades[-1]["elements"].extend(s["elements"])
        else:
            fusionades.append(s)
    n_estrofa = 0
    for s in fusionades:
        s["elements"].sort()
        s["start"] = elements[s["elements"][0]]["start"]
        s["end"] = elements[s["elements"][-1]]["end"]
        if s["label"] == "Estrofa":
            n_estrofa += 1
            s["name"] = f"Estrofa {n_estrofa}"
        else:
            s["name"] = s["label"]

    # Línies que canvien de tipus o de tram
    abans = {i: (seccions[seccio_de[i]]["label"], seccions[seccio_de[i]]["elements"][0]) for i in seccio_de}
    despres = {i: (s["label"], s["elements"][0]) for s in fusionades for i in s["elements"]}
    canvis = sum(abans.get(i) != despres.get(i) for i in linies)
    return fusionades, canvis
