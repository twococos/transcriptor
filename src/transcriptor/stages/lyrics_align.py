"""Etapa lyrics_align: temps per paraula del text conegut a partir de l'ASR.

Alinea les subparaules normalitzades del text amb les de l'ASR (Needleman-Wunsch amb coincidència
aproximada), copia els temps de les parelles i interpola la resta. A la Fase 0 va donar un error
d'inici de línia de 0,17-0,40 s de mediana, mentre que l'alineació forçada de stable-ts col·lapsava.
"""

from __future__ import annotations

from difflib import SequenceMatcher

import numpy as np

from ..text import normalitza

LLINDAR_SIMILITUD = 0.6
FORAT = -0.5
BLOC_NO_CANTAT = 4
MAX_PAS_INTERPOLACIO = 0.4  # segons per subparaula interpolada
MAX_BUIT_LINIA_S = 6.0  # dins d'una línia, un buit més llarg indica paraules mal aparellades


def _similitud(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _aparella(ref: list[str], hip: list[str]) -> list[int | None]:
    """Per a cada element de `ref`, l'índex aparellat de `hip` (o None)."""
    n, m = len(ref), len(hip)
    if n == 0 or m == 0:
        return [None] * n
    sim = np.zeros((n, m), dtype=np.float32)
    cache: dict[tuple[str, str], float] = {}
    for i, a in enumerate(ref):
        for j, b in enumerate(hip):
            # Filtre ràpid: paraules de longitud molt diferent no poden arribar al llindar
            if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.6:
                continue
            clau = (a, b)
            if clau not in cache:
                cache[clau] = _similitud(a, b)
            sim[i, j] = cache[clau]
    punts = np.zeros((n + 1, m + 1), dtype=np.float32)
    punts[:, 0] = FORAT * np.arange(n + 1)
    punts[0, :] = FORAT * np.arange(m + 1)
    dir_ = np.zeros((n + 1, m + 1), dtype=np.int8)  # 0 diagonal, 1 amunt, 2 esquerra
    for i in range(1, n + 1):
        s = sim[i - 1]
        diag_guany = np.where(s >= LLINDAR_SIMILITUD, 2 * s, -1.0)
        for j in range(1, m + 1):
            d = punts[i - 1, j - 1] + diag_guany[j - 1]
            u = punts[i - 1, j] + FORAT
            e = punts[i, j - 1] + FORAT
            if d >= u and d >= e:
                punts[i, j], dir_[i, j] = d, 0
            elif u >= e:
                punts[i, j], dir_[i, j] = u, 1
            else:
                punts[i, j], dir_[i, j] = e, 2
    parella: list[int | None] = [None] * n
    # Final lliure a la banda del text: si el text té línies de més al final (LRC d'una versió més
    # llarga), no es penalitzen. Sense això, el final de l'ASR ("…i ens podrem alliberar") s'aparella
    # amb l'última repetició del text en lloc de la que es canta de veritat.
    i = int(np.argmax(punts[:, m]))  # en cas d'empat, el primer: el text cantat més aviat
    j = m
    while i > 0 and j > 0:
        if dir_[i, j] == 0:
            if sim[i - 1, j - 1] >= LLINDAR_SIMILITUD:
                parella[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif dir_[i, j] == 1:
            i -= 1
        else:
            j -= 1
    return parella


def alinea(linies: list[list[str]], paraules_asr: list[dict], durada: float,
           descarta_no_cantades: bool = True) -> dict:
    """Temps per a cada paraula visible del text.

    Retorna {"paraules": [{start, end, text, conf}], "linies": [[inici, fi)], "aparellades": float,
    "descartades": [text de les línies no cantades]}.
    `conf` és la confiança de l'ASR per a les paraules aparellades i None per a les interpolades.
    """
    # Subparaules del text, amb la paraula visible a què pertanyen
    visibles: list[str] = []
    linies_rang: list[tuple[int, int]] = []
    ref, propietari = [], []
    for linia in linies:
        inici = len(visibles)
        for p in linia:
            for sub in normalitza(p):
                ref.append(sub)
                propietari.append(len(visibles))
            visibles.append(p)
        linies_rang.append((inici, len(visibles)))

    hip, temps_hip = [], []
    for w in paraules_asr:
        for sub in normalitza(w["text"]):
            hip.append(sub)
            temps_hip.append((w["start"], w["end"], w.get("conf")))

    parella = _aparella(ref, hip)
    inici_sub: list[float | None] = [temps_hip[j][0] if j is not None else None for j in parella]
    fi_sub: list[float | None] = [temps_hip[j][1] if j is not None else None for j in parella]
    conf_sub = [temps_hip[j][2] if j is not None else None for j in parella]

    # Interpolació lineal de les subparaules sense parella entre les veïnes conegudes
    coneguts = [k for k, t in enumerate(inici_sub) if t is not None]
    for k in range(len(ref)):
        if inici_sub[k] is not None:
            continue
        ant = max((c for c in coneguts if c < k), default=None)
        seg = min((c for c in coneguts if c > k), default=None)
        if ant is not None and seg is not None:
            # A ritme de parla just després de la paraula coneguda: si el buit és llarg (un tram
            # instrumental), repartir-les uniformement estiraria la línia i hi cauria tot l'instrumental
            t0, t1 = fi_sub[ant], inici_sub[seg]
            pas = min((t1 - t0) / (seg - ant), MAX_PAS_INTERPOLACIO)
            t = t0 + pas * (k - ant)
        elif ant is not None:
            t = min(fi_sub[ant] + 0.3 * (k - ant), durada)
        elif seg is not None:
            t = max(inici_sub[seg] - 0.3 * (seg - k), 0.0)
        else:
            t = durada * k / max(len(ref), 1)
        inici_sub[k] = fi_sub[k] = t

    sortida = []
    for v, text in enumerate(visibles):
        subs = [k for k, p in enumerate(propietari) if p == v]
        if not subs:  # paraula sense lletres (p. ex. "-"): s'enganxa a l'anterior
            t = sortida[-1]["end"] if sortida else 0.0
            sortida.append({"start": t, "end": t, "text": text, "conf": None})
            continue
        confs = [conf_sub[k] for k in subs if conf_sub[k] is not None]
        sortida.append({
            "start": round(min(inici_sub[k] for k in subs), 2),
            "end": round(max(fi_sub[k] for k in subs), 2),
            "text": text,
            "conf": round(float(np.mean(confs)), 3) if confs else None,
        })
    # Línies no cantades: les del final sense cap paraula aparellada, i els blocs de
    # BLOC_NO_CANTAT línies seguides sense cap paraula aparellada (estrofa d'una altra versió)
    aparellades_linia = [sum(1 for v in range(a, b) if (sortida[v]["conf"] is not None)) for a, b in linies_rang]
    cantada = [True] * len(linies_rang)
    if descarta_no_cantades and any(aparellades_linia):
        ultima = max(k for k, n_ap in enumerate(aparellades_linia) if n_ap)
        for k in range(ultima + 1, len(cantada)):
            cantada[k] = False
        k = 0
        while k <= ultima:
            if aparellades_linia[k] == 0:
                fi = k
                while fi <= ultima and aparellades_linia[fi] == 0:
                    fi += 1
                if fi - k >= BLOC_NO_CANTAT:
                    for x in range(k, fi):
                        cantada[x] = False
                k = fi
            else:
                k += 1

    # Una línia no té buits llargs entre paraules: si n'hi ha, les paraules d'abans del buit estan
    # mal aparellades (p. ex. "Al" de "Al bell mig…" aparellat amb un "al" anterior) i s'acosten
    for a, b in linies_rang:
        for k in range(b - 2, a - 1, -1):
            seguent = sortida[k + 1]["start"]
            if seguent - sortida[k]["end"] > MAX_BUIT_LINIA_S:
                for x in range(k, a - 1, -1):
                    durada_w = min(max(sortida[x]["end"] - sortida[x]["start"], 0.15), MAX_PAS_INTERPOLACIO)
                    sortida[x]["end"] = round(seguent - 0.05, 2)
                    sortida[x]["start"] = round(sortida[x]["end"] - durada_w, 2)
                    seguent = sortida[x]["start"]
                break

    paraules_finals, linies_finals, descartades = [], [], []
    for k, (a, b) in enumerate(linies_rang):
        if not cantada[k]:
            descartades.append(" ".join(visibles[a:b]))
            continue
        inici = len(paraules_finals)
        paraules_finals.extend(sortida[a:b])
        linies_finals.append([inici, len(paraules_finals)])
    return {
        "paraules": paraules_finals,
        "linies": linies_finals,
        "aparellades": round(len(coneguts) / max(len(ref), 1), 3),
        "descartades": descartades,
    }
