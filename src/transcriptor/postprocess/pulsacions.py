"""Correcció de la graella de pulsacions de Beat This! abans de numerar el compàs (meter.py).

Errades típiques del model (mesurades a Comèdia dramàtica, Torno a ser jo, La cançó del lladre…):
- Pulsacions falses en fills i finals de frase: dos intervals que sumen una pulsació (0.26 + 0.08 s a
  176 BPM) o un tram curt a doble tempo. meter.py les compta com a temps i el compàs "s'accelera"; el
  comptador queda desplaçat i els inicis de compàs van creuats fins a la següent errada.
- Trams sencers a doble o meitat de tempo (Efaristo, Lloverá y yo veré).

El repertori és pop amb tempo constant: s'imposa una graella regular allà on encaixa i es deixa el cru
on no (ritardando, calderó, canvi de tempo real). Els compassos irregulars reals (Mari Carmen) no es
toquen: la graella hi és regular, el que canvia és el compàs, i això ho decideix meter.py.

Passos: (1) octava majoritària i trams a doble/meitat de tempo; (2) forats entre trams regulars
(ancoratges) que encaixen amb un nombre enter de pulsacions; (3) intro i outro, només si ja seguien la
graella; (4) es descarten els inicis de compàs de dins els forats refets.
"""

from __future__ import annotations

import numpy as np

FINESTRA_LOCAL = 4  # intervals a cada costat per al període local
TOL_OCTAVA = 0.25  # en log2: una banda de tempo és ±19 %
EMPAT_OCTAVA = 1.15  # si la segona octava té més d'1/1.15 de la durada de la primera, desempata el prior
BPM_PRIOR = 115.0
MIN_TRAM_OCTAVA = 4.0  # durada mínima (en pulsacions de referència) d'un tram a doble/meitat de tempo
TOL_REGULAR = 0.12
MIN_ANCORA = 6  # intervals regulars seguits
TOL_ENCAIX = 0.1  # residu de la graella comuna a dos ancoratges, en pulsacions
TOL_MATEIX_TEMPO = 0.06
MAX_FORAT = 64  # pulsacions
PULSACIONS_PERIODE = 16  # intervals de l'ancoratge per estimar-ne el període
TOL_EXTREM = 0.15  # fracció de pulsació
MIN_EXTREM_ALINEADES = 0.75


def _periode_local(ibi: np.ndarray) -> np.ndarray:
    n = len(ibi)
    return np.array([np.median(ibi[max(0, i - FINESTRA_LOCAL): i + FINESTRA_LOCAL + 1]) for i in range(n)])


def _periode_referencia(ibi: np.ndarray, local: np.ndarray) -> float:
    """Període de l'octava que ocupa més temps (no més pulsacions: un tram a doble tempo en té el doble)."""
    t0 = float(np.median(ibi))
    candidats = []
    for c in (t0 / 2, t0, 2 * t0):
        dins = np.abs(np.log2(local / c)) < TOL_OCTAVA
        if dins.any():
            candidats.append((float(ibi[dins].sum()), float(np.mean(ibi[dins]))))
    candidats.sort(reverse=True)
    if len(candidats) > 1 and candidats[0][0] < EMPAT_OCTAVA * candidats[1][0]:
        candidats = sorted(candidats[:2], key=lambda c: abs(np.log2(60.0 / c[1] / BPM_PRIOR)))
    return candidats[0][1]


def _trams(mascara: np.ndarray) -> list[tuple[int, int]]:
    """Trams [inici, fi) de valors certs seguits."""
    trams, inici = [], None
    for i, v in enumerate(mascara):
        if v and inici is None:
            inici = i
        elif not v and inici is not None:
            trams.append((inici, i))
            inici = None
    if inici is not None:
        trams.append((inici, len(mascara)))
    return trams


def _corregeix_octava(p: np.ndarray, tref: float) -> tuple[np.ndarray, list[dict]]:
    ibi = np.diff(p)
    rel = np.log2(_periode_local(ibi) / tref)
    correccions = []
    canvis: list[tuple[int, int, np.ndarray]] = []  # (primera pulsació, última, pulsacions noves)
    for factor, mascara in ((0.5, np.abs(rel + 1) < TOL_OCTAVA), (2.0, np.abs(rel - 1) < TOL_OCTAVA)):
        for a, b in _trams(mascara):
            # Intervals [a, b) → pulsacions a..b
            if p[b] - p[a] < MIN_TRAM_OCTAVA * tref:
                continue
            tram = p[a: b + 1]
            if factor == 0.5:
                # Una de cada dues: la paritat que millor continua la graella d'abans (o la de després)
                if a > 0:
                    ref, signe = p[a - 1], 1
                elif b + 1 < len(p):
                    ref, signe = p[b + 1], -1
                else:
                    ref, signe = tram[0], 1
                millor = None
                for paritat in (0, 1):
                    escollides = tram[paritat::2]
                    fase = ((escollides - ref) * signe / tref) % 1.0
                    error = float(np.minimum(fase, 1 - fase).sum())
                    if millor is None or error < millor[0]:
                        millor = (error, escollides)
                nou = millor[1]
            else:
                nou = np.sort(np.concatenate([tram, (tram[:-1] + tram[1:]) / 2]))
            canvis.append((a, b, nou))
            correccions.append({"tipus": "octava", "inici": round(float(p[a]), 3), "fi": round(float(p[b]), 3),
                                "abans": len(tram), "despres": len(nou)})
    if not canvis:
        return p, []
    parts, cursor = [], 0
    for a, b, nou in sorted(canvis, key=lambda c: c[0]):
        if a < cursor:  # solapament entre un tram ràpid i un de lent: es descarta el segon
            continue
        parts += [p[cursor:a], nou]
        cursor = b + 1
    parts.append(p[cursor:])
    return np.concatenate(parts), correccions


def _ancoratges(p: np.ndarray, tref: float) -> list[tuple[int, int]]:
    """Trams de pulsacions [primera, última] amb ≥ MIN_ANCORA intervals regulars seguits."""
    ibi = np.diff(p)
    propers = np.abs(ibi / tref - 1) < TOL_REGULAR
    local = np.full(len(ibi), tref)
    for i in range(len(ibi)):
        fin = propers[max(0, i - 8): i + 9]
        if fin.any():
            local[i] = np.median(ibi[max(0, i - 8): i + 9][fin])
    regular = np.abs(ibi / local - 1) < TOL_REGULAR
    return [(a, b) for a, b in _trams(regular) if b - a >= MIN_ANCORA]


def _recta(p: np.ndarray, s: int, e: int, final: bool) -> tuple[float, float]:
    """(Temps de la vora, període) de la recta ajustada a les darreres (o primeres) pulsacions d'un
    ancoratge. Beat This! dona temps quantitzats a 0.02 s: la pulsació de la vora sola o la mediana dels
    intervals (0.52 en lloc de 0.5275) desquadren un forat de 27 pulsacions."""
    vora = e if final else s
    if final:
        idx = np.arange(max(s, e - PULSACIONS_PERIODE), e + 1)
    else:
        idx = np.arange(s, min(e, s + PULSACIONS_PERIODE) + 1)
    periode, origen = np.polyfit(idx, p[idx], 1)
    return float(origen + periode * vora), float(periode)


def _error_graella(p: np.ndarray, anc_a: tuple[int, int], anc_b: tuple[int, int]) -> tuple[int, float] | None:
    """(n, error): n = pulsacions entre el final de l'ancoratge A i l'inici del B que fan que tots dos
    caiguin sobre una mateixa graella; error = residu quadràtic mitjà d'aquesta graella, en pulsacions.
    None si els dos ancoratges no van al mateix tempo."""
    (s1, e1), (s2, e2) = anc_a, anc_b
    a, ta = _recta(p, s1, e1, final=True)
    b, tb = _recta(p, s2, e2, final=False)
    if abs(ta / tb - 1) > TOL_MATEIX_TEMPO:
        return None
    x = (b - a) / ((ta + tb) / 2)
    ia = np.arange(max(s1, e1 - PULSACIONS_PERIODE), e1 + 1)
    ib = np.arange(s2, min(e2, s2 + PULSACIONS_PERIODE) + 1)
    temps = np.concatenate([p[ia], p[ib]])
    millor = None
    for n in {int(np.floor(x)), int(np.ceil(x))}:
        if not 1 <= n <= MAX_FORAT:
            continue
        k = np.concatenate([ia - e1, ib - s2 + n])  # número de pulsació sobre la graella comuna
        periode, origen = np.polyfit(k, temps, 1)
        error = float(np.sqrt(np.mean((temps - origen - periode * k) ** 2)) / periode)
        if millor is None or error < millor[1]:
            millor = (n, error)
    return millor


def _omple_forats(p: np.ndarray, tref: float) -> tuple[np.ndarray, list[tuple[float, float]], list[dict]]:
    ancoratges = _ancoratges(p, tref)
    parts, cursor, forats, correccions = [], 0, [], []
    i = 0
    while i < len(ancoratges) - 1:
        # El forat pot saltar ancoratges curts al mateix tempo però desfasats (Beat This! seguint el
        # contratemps uns segons): el que mana és que A i el següent ancoratge que encaixi quadrin
        s1, e1 = ancoratges[i]
        ta = _recta(p, s1, e1, final=True)[1]
        trobat = None
        for j in range(i + 1, len(ancoratges)):
            if p[ancoratges[j][0]] - p[e1] > MAX_FORAT * ta:
                break
            encaix = _error_graella(p, ancoratges[i], ancoratges[j])
            if encaix is not None and encaix[1] <= TOL_ENCAIX:
                trobat = (j, encaix[0])
                break
            s, e = ancoratges[j]
            if abs((p[e] - p[s]) / (e - s) / ta - 1) > TOL_MATEIX_TEMPO:
                break  # un tram a un altre tempo no es salta
        if trobat is None:
            i += 1
            continue
        j, n = trobat
        s2 = ancoratges[j][0]
        a, b = p[e1], p[s2]
        nou = np.linspace(a, b, n + 1)[1:-1]
        vell = p[e1 + 1: s2]
        i = j
        if len(vell) == len(nou) and (len(nou) == 0 or np.abs(vell - nou).max() < TOL_REGULAR * (b - a) / n):
            continue  # ja era bona
        parts += [p[cursor: e1 + 1], nou]
        cursor = s2
        forats.append((float(a), float(b)))
        correccions.append({"tipus": "forat", "inici": round(float(a), 3), "fi": round(float(b), 3),
                            "abans": len(vell), "despres": len(nou)})
    parts.append(p[cursor:])
    return np.concatenate(parts), forats, correccions


def _corregeix_extrem(cru: np.ndarray, vora: float, t: float, signe: int) -> np.ndarray | None:
    """Graella extrapolada des de `vora` cap enfora (signe -1 = intro) si les pulsacions crues ja la seguien."""
    if len(cru) == 0:
        return None
    llunyana = cru.min() if signe < 0 else cru.max()
    k = int(np.floor(abs(llunyana - vora) / t + TOL_EXTREM))
    if k < 1:
        return None
    graella = vora + signe * t * np.arange(1, k + 1)
    distancia = np.abs(cru[:, None] - graella[None, :]).min(axis=1)
    if np.mean(distancia < TOL_EXTREM * t) < MIN_EXTREM_ALINEADES:
        return None
    if len(graella) == len(cru) and np.abs(np.sort(graella) - cru).max() < TOL_EXTREM * t:
        return None  # ja era bona
    return np.sort(graella)


def _corregeix_extrems(p: np.ndarray, tref: float) -> tuple[np.ndarray, list[dict]]:
    ancoratges = _ancoratges(p, tref)
    if not ancoratges:
        return p, []
    correccions = []
    (s1, e1), (s2, e2) = ancoratges[0], ancoratges[-1]
    final = None
    if e2 < len(p) - 1:
        final = _corregeix_extrem(p[e2 + 1:], *_recta(p, s2, e2, final=True), 1)
    inici = None
    if s1 > 0:
        inici = _corregeix_extrem(p[:s1], *_recta(p, s1, e1, final=False), -1)
    if final is not None:
        correccions.append({"tipus": "extrem", "inici": round(float(p[e2]), 3), "fi": round(float(p[-1]), 3),
                            "abans": len(p) - 1 - e2, "despres": len(final)})
        p = np.concatenate([p[: e2 + 1], final])
    if inici is not None:
        correccions.insert(0, {"tipus": "extrem", "inici": round(float(p[0]), 3), "fi": round(float(p[s1]), 3),
                               "abans": s1, "despres": len(inici)})
        p = np.concatenate([inici, p[s1:]])
    return p, correccions


def corregeix(pulsacions: list[float], inicis_compas: list[float]) -> dict:
    """Retorna {"pulsacions", "inicis_compas", "correccions": [{tipus, inici, fi, abans, despres}]}."""
    p = np.asarray(pulsacions, dtype=float)
    if len(p) < 2 * MIN_ANCORA + 4:
        return {"pulsacions": list(pulsacions), "inicis_compas": list(inicis_compas), "correccions": []}
    ibi = np.diff(p)
    tref = _periode_referencia(ibi, _periode_local(ibi))

    p, correccions = _corregeix_octava(p, tref)
    p, forats, c = _omple_forats(p, tref)
    correccions += c
    p, c = _corregeix_extrems(p, tref)
    correccions += c

    # Els inicis de compàs de dins un forat refet es van predir sobre pulsacions errònies
    inicis = [t for t in inicis_compas if not any(a < t < b for a, b in forats)]
    correccions.sort(key=lambda c: c["inici"])
    return {"pulsacions": [round(float(t), 3) for t in p], "inicis_compas": inicis, "correccions": correccions}
