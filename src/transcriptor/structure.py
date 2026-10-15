"""Detecció pròpia de seccions (substitueix allin1).

1. Les línies s'agrupen en blocs separats per silencis vocals llargs o zones instrumentals.
2. Una línia és "repetida" si n'hi ha una altra amb text gairebé igual en un altre lloc.
3. Dins de cada bloc, els trams de línies repetides que tornen a aparèixer com a grup són la
   **Tornada**; la resta són **Estrofes** (numerades). Un bloc no repetit cap al final amb acords
   que no surten enlloc més és un **Pont**.
4. Abans de la primera veu: **Intro**. Després de l'última: **Outro**. Al mig: **Instrumental**.

Noms segons SECTION_TYPES de src/lib/editor/sections.ts del canconer.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .text import normalitza

SECTION_TYPES = ["Estrofa", "Tornada", "Pre-tornada", "Pont", "Solo", "Instrumental", "Interludi",
                 "Intro", "Outro"]

SIMILITUD_LINIA = 0.75
BUIT_BLOC_S = 2.5
MIN_LINIES_TRAM = 2
FRACCIO_FINAL_PONT = 0.55


def _clau(text: str) -> str:
    return " ".join(normalitza(text))


def _similars(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a == b or SequenceMatcher(None, a, b, autojunk=False).ratio() >= SIMILITUD_LINIA


def _acords(elements: list[dict], idx: list[int]) -> set[str]:
    return {ac[1] for i in idx for ac in elements[i].get("acords", [])}


def detecta(elements: list[dict], durada: float, durada_compas: float) -> list[dict]:
    """Assigna seccions. Retorna [{start, end, label, name, elements: [índexs]}] en ordre."""
    idx_linies = [i for i, e in enumerate(elements) if e["tipus"] == "linia"]
    claus = {i: _clau(elements[i]["text"]) for i in idx_linies}

    # 1. Blocs de línies (una zona instrumental o un silenci llarg tanquen el bloc)
    blocs: list[list[int]] = []
    actual: list[int] = []
    anterior_fi = None
    for i, e in enumerate(elements):
        if e["tipus"] == "instrumental":
            if actual:
                blocs.append(actual)
                actual = []
            continue
        if actual and anterior_fi is not None and e["start"] - anterior_fi > max(BUIT_BLOC_S, durada_compas * 1.5):
            blocs.append(actual)
            actual = []
        actual.append(i)
        anterior_fi = e["end"]
    if actual:
        blocs.append(actual)

    # 2. Línies repetides
    repetida = {i: any(_similars(claus[i], claus[j]) for j in idx_linies if abs(j - i) > 1)
                for i in idx_linies}

    # 3. Trams dins de cada bloc segons si les línies són repetides
    trams: list[tuple[list[int], bool]] = []
    for bloc in blocs:
        parts: list[tuple[list[int], bool]] = []
        for i in bloc:
            if parts and parts[-1][1] == repetida[i]:
                parts[-1][0].append(i)
            else:
                parts.append(([i], repetida[i]))
        # Trams massa curts s'enganxen a l'anterior (o al següent si són el primer)
        net: list[tuple[list[int], bool]] = []
        for p in parts:
            if len(p[0]) < MIN_LINIES_TRAM and net:
                net[-1][0].extend(p[0])
            else:
                net.append(p)
        if len(net) > 1 and len(net[0][0]) < MIN_LINIES_TRAM:
            primer = net.pop(0)
            net[0] = (primer[0] + net[0][0], net[0][1])
        trams.extend(net)

    # Un tram "repetit" només és tornada si el grup es repeteix (≥ la meitat de línies a un altre tram)
    def es_tornada(k: int) -> bool:
        linies_k = [claus[i] for i in trams[k][0]]
        for j, (altres, _) in enumerate(trams):
            if j == k:
                continue
            coincidents = sum(any(_similars(c, claus[o]) for o in altres) for c in linies_k)
            if coincidents >= max(2, len(linies_k) // 2):
                return True
        return False

    tipus = ["Tornada" if rep and es_tornada(k) else "Estrofa" for k, (_, rep) in enumerate(trams)]

    # Pre-tornada: dins d'una tornada, les línies inicials que es repeteixen menys vegades que el
    # nucli (p. ex. "A la deriva": "Atrapar la lluna…" surt 2 cops i "Uoh, que la vida…" 3 cops)
    def repeticions(i: int) -> int:
        return sum(_similars(claus[i], claus[j]) for j in idx_linies)

    nous_trams, nous_tipus = [], []
    for (idx, rep), t in zip(trams, tipus):
        if t == "Tornada" and len(idx) >= 2 * MIN_LINIES_TRAM:
            rep_linia = [repeticions(i) if elements[i]["tipus"] == "linia" else 0 for i in idx]
            nucli = max(rep_linia)
            tall = next((k for k, r in enumerate(rep_linia) if r == nucli), 0)
            if tall >= MIN_LINIES_TRAM and len(idx) - tall >= MIN_LINIES_TRAM:
                nous_trams += [(idx[:tall], rep), (idx[tall:], rep)]
                nous_tipus += ["Pre-tornada", "Tornada"]
                continue
        nous_trams.append((idx, rep))
        nous_tipus.append(t)
    trams, tipus = nous_trams, nous_tipus

    # Pont: tram d'estrofa únic cap al final, després d'una tornada, amb acords nous
    for k, (idx, _) in enumerate(trams):
        if tipus[k] != "Estrofa" or "Tornada" not in tipus[:k]:
            continue
        if elements[idx[0]]["start"] < durada * FRACCIO_FINAL_PONT:
            continue
        altres = set().union(*(_acords(elements, t[0]) for j, t in enumerate(trams) if j != k))
        if _acords(elements, idx) - altres:
            tipus[k] = "Pont"

    # 4. Seccions finals, incloent-hi les zones instrumentals
    seccions: list[dict] = []
    for k, (idx, _) in enumerate(trams):
        seccions.append({"label": tipus[k], "elements": idx})
    for i, e in enumerate(elements):
        if e["tipus"] != "instrumental":
            continue
        if e["end"] - e["start"] < durada_compas * 0.9 and len(e["acords"]) < 2:
            # Massa curt per ser secció: s'afegeix a la secció veïna
            seccions.append({"label": None, "elements": [i]})
            continue
        if not idx_linies or i < idx_linies[0]:
            etiqueta = "Intro"
        elif i > idx_linies[-1]:
            etiqueta = "Outro"
        else:
            etiqueta = "Instrumental"
        seccions.append({"label": etiqueta, "elements": [i]})
    seccions.sort(key=lambda s: s["elements"][0])

    # Zones curtes sense etiqueta: s'uneixen a l'anterior (o a la següent si són al principi)
    fusionades: list[dict] = []
    pendents: list[int] = []
    for s in seccions:
        if s["label"] is None:
            if fusionades:
                fusionades[-1]["elements"].extend(s["elements"])
            else:
                pendents.extend(s["elements"])
            continue
        if pendents:
            s["elements"] = pendents + s["elements"]
            pendents = []
        # Dues seccions consecutives del mateix tipus no repetible s'uneixen
        if fusionades and fusionades[-1]["label"] == s["label"] and s["label"] in ("Instrumental", "Pont"):
            fusionades[-1]["elements"].extend(s["elements"])
        else:
            fusionades.append(s)
    if pendents:
        fusionades.append({"label": "Intro", "elements": pendents})

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
    return fusionades
