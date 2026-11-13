"""Postprocés d'acords: de probabilitats per trama (BTC) a acords per pulsació.

1. Les 170 classes es col·lapsen al vocabulari triat (majmin | sevenths | full) sumant-ne les
   probabilitats ("A:7" i "A:maj7" compten per a "A" en majmin).
2. Es fa la mitjana de probabilitats dins de cada pulsació (unitat mínima = 1 pulsació, així
   desapareixen els acords de menys d'una pulsació).
3. Viterbi per compàs (`viterbi_compas`): cada compàs tria un patró de divisió (4, 2+2, 1+1+1+1...)
   i un acord per tros. Així els canvis cauen a terra o a mig compàs, els acords de pas d'un
   compàs duren el mateix (els patrons irregulars són cars) i un acord d'un temps aïllat només
   surt si l'evidència és forta: BTC sovint canvia un temps tard o d'hora per com és
   l'acompanyament. Sense compàs (poques pulsacions), Viterbi per pulsació (`viterbi`) amb la
   penalització per canvi més baixa a l'inici de compàs.
"""

from __future__ import annotations

import numpy as np

from ..notation import de_harte
from ..vendor.btc import idx_a_acord

PENALITZACIO_CANVI = 2.0
FACTOR_INICI_COMPAS = 0.35  # la penalització a l'inici de compàs es multiplica per això
PES_SEPTIMES = 0.3  # prior: BTC sobreprediu sèptimes; el guitarrista les escriu menys
SENSE_ACORD = "N"

# Patrons de divisió del compàs (en pulsacions) i cost de cadascun, per nombre de pulsacions del
# compàs. Els trossos només comencen a terra o a mig compàs, tret dels patrons de temps solts, i
# dins el compàs cada tros és un acord diferent de l'anterior.
PENALITZACIO_CANVI_COMPAS = 0.7  # per canvi d'acord entre trossos (a més del cost del patró)
PATRONS: dict[int, list[tuple[tuple[int, ...], float]]] = {
    1: [((1,), 0.0)],
    2: [((2,), 0.0), ((1, 1), 1.5)],
    3: [((3,), 0.0), ((2, 1), 2.0), ((1, 2), 2.0), ((1, 1, 1), 2.5)],
    4: [((4,), 0.0), ((2, 2), 1.0), ((1, 1, 1, 1), 3.0), ((2, 1, 1), 3.5), ((1, 1, 2), 3.5)],
    6: [((6,), 0.0), ((3, 3), 1.0), ((2, 2, 2), 3.0)],
}
COST_TEMPS_SOLTS = 3.0  # compassos irregulars: o un sol acord o un acord per pulsació


def vocabulari(nivell: str) -> tuple[list[str], np.ndarray]:
    """Etiquetes del vocabulari i matriu [170, n_etiquetes] de col·lapse (amb el prior de sèptimes)."""
    etiquetes: list[str] = []
    files = []
    for i in range(170):
        e = de_harte(idx_a_acord(i), nivell) or SENSE_ACORD
        if e not in etiquetes:
            etiquetes.append(e)
        files.append(etiquetes.index(e))
    m = np.zeros((170, len(etiquetes)), dtype=np.float32)
    for i, j in enumerate(files):
        sufix = etiquetes[j].lstrip("ABCDEFG#")
        m[i, j] = PES_SEPTIMES if sufix in ("7", "maj7", "m7") else 1.0
    return etiquetes, m


def unitats(pulsacions: list[float], durada: float) -> np.ndarray:
    """Vores de les unitats temporals: [0, p0, p1, ..., pn, final]."""
    p = np.asarray(pulsacions, dtype=float)
    if len(p) == 0:
        return np.array([0.0, durada])
    ibi = float(np.median(np.diff(p))) if len(p) > 1 else 0.5
    final = min(durada, p[-1] + ibi) if durada > p[-1] else p[-1] + ibi
    vores = np.concatenate([[0.0], p, [final]])
    # Si la primera pulsació és a l'inici, no cal la unitat [0, p0)
    return vores[1:] if p[0] < 0.05 else vores


def probabilitats_per_unitat(probs: np.ndarray, per_trama: float, vores: np.ndarray,
                             col_lapse: np.ndarray) -> np.ndarray:
    """[unitats, etiquetes] amb la mitjana de probabilitats col·lapsades dins de cada unitat."""
    p_et = probs @ col_lapse
    p_et /= p_et.sum(axis=1, keepdims=True) + 1e-9
    sortida = np.zeros((len(vores) - 1, p_et.shape[1]), dtype=np.float32)
    for u in range(len(vores) - 1):
        a = int(vores[u] / per_trama)
        b = max(int(np.ceil(vores[u + 1] / per_trama)), a + 1)
        tros = p_et[a:b]
        sortida[u] = tros.mean(axis=0) if len(tros) else sortida[u - 1] if u else 1.0 / p_et.shape[1]
    return sortida


def viterbi(p_unitat: np.ndarray, inici_compas: np.ndarray, penalitzacio: float | None = None) -> np.ndarray:
    """Seqüència d'etiquetes (índexs) que maximitza Σ log p − penalització·canvis."""
    penalitzacio = PENALITZACIO_CANVI if penalitzacio is None else penalitzacio
    logp = np.log(p_unitat + 1e-6)
    n, k = logp.shape
    punts = logp[0].copy()
    previ = np.zeros((n, k), dtype=np.int32)
    for u in range(1, n):
        pen = penalitzacio * (FACTOR_INICI_COMPAS if inici_compas[u] else 1.0)
        millor_anterior = int(np.argmax(punts))
        canvi = punts[millor_anterior] - pen
        queda = punts >= canvi
        previ[u] = np.where(queda, np.arange(k), millor_anterior)
        punts = np.where(queda, punts, canvi) + logp[u]
    cami = np.zeros(n, dtype=np.int32)
    cami[-1] = int(np.argmax(punts))
    for u in range(n - 1, 0, -1):
        cami[u - 1] = previ[u, cami[u]]
    return cami


def _patrons(n: int) -> list[tuple[tuple[int, ...], float]]:
    if n in PATRONS:
        return PATRONS[n]
    return [((n,), 0.0), ((1,) * n, COST_TEMPS_SOLTS)]


def _grups(beats: list[dict], desfasament: int, n_unitats: int) -> list[tuple[int, int]]:
    """Rangs d'unitats [a, b) de cada compàs. La unitat [0, p0) va sola."""
    grups = [(0, desfasament)] if desfasament else []
    inici = desfasament
    for i in range(1, len(beats)):
        if beats[i]["beat"] == 1:
            grups.append((inici, i + desfasament))
            inici = i + desfasament
    grups.append((inici, n_unitats))
    return [g for g in grups if g[1] > g[0]]


def viterbi_compas(p_unitat: np.ndarray, beats: list[dict], desfasament: int,
                   bonificacio: np.ndarray | None = None) -> np.ndarray:
    """Seqüència d'etiquetes (índexs per unitat) amb un patró de divisió per compàs.

    Maximitza Σ log p − cost dels patrons − PENALITZACIO_CANVI_COMPAS·canvis. L'estat entre
    compassos és l'últim acord; dins el compàs, tros a tros amb el truc O(K) de `viterbi`.
    `bonificacio` (unitats × etiquetes) se suma a log p: els vots de les fonts externes (fonts/consens.py).
    """
    logp = np.log(p_unitat + 1e-6)
    if bonificacio is not None:
        logp = logp + bonificacio
    n, k = logp.shape
    punts = np.zeros(k)
    rastre = []  # per compàs: (patró triat per acord final, [per patró: [(a, b, previ[k])]])
    for a, b in _grups(beats, desfasament, n):
        millor = np.full(k, -np.inf)
        tria = np.zeros(k, dtype=np.int32)
        trossos_patrons = []
        for j, (patro, cost) in enumerate(_patrons(b - a)):
            v, trossos, x = punts, [], a
            for t, llarg in enumerate(patro):
                s = logp[x:x + llarg].sum(axis=0)
                m = int(np.argmax(v))
                canvi = v[m] - PENALITZACIO_CANVI_COMPAS
                if t == 0:
                    queda = v >= canvi
                    previ = np.where(queda, np.arange(k), m)
                    v = np.where(queda, v, canvi)
                else:
                    # Dins el compàs cada tros canvia d'acord: si no, el patró real seria un altre
                    # (A E E E no és 1+1+2 sinó 1+3, que no s'admet)
                    v2 = v.copy()
                    v2[m] = -np.inf
                    m2 = int(np.argmax(v2))
                    previ = np.full(k, m)
                    previ[m] = m2
                    v = v[previ] - PENALITZACIO_CANVI_COMPAS
                trossos.append((x, x + llarg, previ))
                v = v + s
                x += llarg
            v = v - cost
            trossos_patrons.append(trossos)
            millors = v > millor
            millor = np.where(millors, v, millor)
            tria = np.where(millors, j, tria)
        rastre.append((tria, trossos_patrons))
        punts = millor
    cami = np.zeros(n, dtype=np.int32)
    c = int(np.argmax(punts))
    for tria, trossos_patrons in reversed(rastre):
        for x, y, previ in reversed(trossos_patrons[tria[c]]):
            cami[x:y] = c
            c = int(previ[c])
    return cami


def canvis_crus(p_unitat: np.ndarray) -> list[bool]:
    """Per a cada unitat, si l'argmax canvia respecte de l'anterior (evidència per al compàs)."""
    am = p_unitat.argmax(axis=1)
    return [False] + [bool(am[i] != am[i - 1]) for i in range(1, len(am))]


def segments(cami: np.ndarray, etiquetes: list[str], vores: np.ndarray, p_unitat: np.ndarray,
             min_unitats: int = 1, buit_max: float = 1.0) -> list[dict]:
    """Agrupa unitats consecutives amb la mateixa etiqueta; descarta els "N" i els massa curts."""
    sortida = []
    inici = 0
    for u in range(1, len(cami) + 1):
        if u == len(cami) or cami[u] != cami[inici]:
            e = etiquetes[cami[inici]]
            if e != SENSE_ACORD and u - inici >= min_unitats:
                sortida.append({
                    "start": round(float(vores[inici]), 3), "end": round(float(vores[u]), 3),
                    "label": e, "conf": round(float(p_unitat[inici:u, cami[inici]].mean()), 3),
                    "unitat": inici,
                })
            inici = u
    # Fusiona acords iguals que han quedat separats per un segment descartat (o un "N" curt)
    fusionats: list[dict] = []
    for s in sortida:
        if fusionats and fusionats[-1]["label"] == s["label"] and s["start"] - fusionats[-1]["end"] < buit_max:
            fusionats[-1]["end"] = s["end"]
        else:
            fusionats.append(s)
    return fusionats
