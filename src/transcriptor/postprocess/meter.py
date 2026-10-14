"""Regularització del compàs a partir de les pulsacions de Beat This!.

Els inicis de compàs que dona Beat This! (postprocessador `minimal`) són erràtics en música
sincopada (Fase 0: "La gent que estimo"). Aquí s'imposa un compàs constant amb un Viterbi:
l'estat de cada pulsació és la seva posició dins el compàs; avançar una posició és gratuït i
qualsevol altre salt (compàs incomplet o canvi de fase) es penalitza. Les evidències són els inicis
de compàs predits i els canvis d'acord (que solen caure a l'inici del compàs).

Compàs compost: si surten 3 pulsacions per compàs a tempo ràpid, és un 6/8 (o 12/8) on Beat This!
compta corxeres (L'estaca); s'agrupen els compassos de dos en dos amb una segona passada.
"""

from __future__ import annotations

import numpy as np

PENALITZACIO_SALT = 3.0
PES_INICI_COMPAS = 1.0
PES_CANVI_ACORD = 0.6
BPM_MIN_COMPOST = 150.0


def _viterbi(evidencia: np.ndarray, m: int, penalitzacio: float) -> tuple[np.ndarray, float]:
    """evidencia[i] = guany si la pulsació i és posició 0. Retorna (posicions, puntuació)."""
    n = len(evidencia)
    punts = np.full((n, m), -np.inf)
    previ = np.zeros((n, m), dtype=np.int16)
    punts[0] = 0.0
    punts[0, 0] = evidencia[0]
    for i in range(1, n):
        for s in range(m):
            natural = (s - 1) % m
            candidats = punts[i - 1] - penalitzacio
            candidats[natural] += penalitzacio
            p = int(np.argmax(candidats))
            punts[i, s] = candidats[p] + (evidencia[i] if s == 0 else 0.0)
            previ[i, s] = p
    pos = np.zeros(n, dtype=np.int16)
    pos[-1] = int(np.argmax(punts[-1]))
    for i in range(n - 1, 0, -1):
        pos[i - 1] = previ[i, pos[i]]
    return pos, float(punts[-1].max())


def _index_mes_proper(pulsacions: np.ndarray, temps: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(pulsacions, temps)
    idx = np.clip(idx, 1, len(pulsacions) - 1)
    esquerra = pulsacions[idx - 1]
    dreta = pulsacions[idx]
    return np.where(np.abs(temps - esquerra) <= np.abs(temps - dreta), idx - 1, idx)


def regularitza(pulsacions: list[float], inicis_compas: list[float], canvis_acord: list[bool]) -> dict:
    """Retorna {"bpm", "time_signature", "beats": [{t, bar, beat}]}.

    `canvis_acord[i]` indica si l'acord canvia a la pulsació i (argmax per pulsació, sense suavitzar).
    """
    p = np.asarray(pulsacions, dtype=float)
    if len(p) < 8:
        return {"bpm": 0.0, "time_signature": [4, 4],
                "beats": [{"t": float(t), "bar": 1, "beat": k + 1} for k, t in enumerate(p)]}
    bpm = 60.0 / float(np.median(np.diff(p)))

    vots_ic = np.zeros(len(p))
    if inicis_compas:
        idx = _index_mes_proper(p, np.asarray(inicis_compas, dtype=float))
        np.add.at(vots_ic, idx, 1.0)
    vots_ac = np.asarray(canvis_acord[: len(p)] + [False] * (len(p) - len(canvis_acord)), dtype=float)
    evidencia = PES_INICI_COMPAS * np.minimum(vots_ic, 1.0) + PES_CANVI_ACORD * vots_ac

    # Tria entre 3 i 4 pulsacions per compàs. La puntuació bruta afavoreix compassos curts (més
    # posicions 0), així que es compara el "guany" respecte de l'esperat per atzar.
    millor = None
    for m in (3, 4):
        pos, _ = _viterbi(evidencia, m, PENALITZACIO_SALT)
        a_zero = evidencia[pos == 0].sum()
        total = evidencia.sum() or 1.0
        guany = (a_zero / total) * m  # 1.0 = atzar
        if millor is None or guany > millor[0] + 0.05:
            millor = (guany, m, pos)
    _, m, pos = millor

    compost = m == 3 and bpm >= BPM_MIN_COMPOST
    if compost:
        # Agrupa compassos de 3 de dos en dos: Viterbi de 2 estats sobre els compassos, amb els canvis
        # d'acord com a evidència (en 6/8 l'harmonia canvia sobretot cada 6 corxeres)
        inicis = np.flatnonzero(pos == 0)
        ev_compas = np.array([vots_ac[i] + 0.5 * min(vots_ic[i], 1.0) for i in inicis])
        pos_compas, _ = _viterbi(ev_compas, 2, PENALITZACIO_SALT)
        nova = np.zeros_like(pos)
        for k, i in enumerate(inicis):
            fi = inicis[k + 1] if k + 1 < len(inicis) else len(pos)
            nova[i:fi] = pos[i:fi] + 3 * pos_compas[k]
        # Pulsacions abans del primer inici de compàs (anacrusi)
        nova[: inicis[0]] = pos[: inicis[0]] + 3
        pos, m = nova, 6

    # Les pulsacions abans del primer inici de compàs (anacrusi) van al compàs 0
    beats, compas = [], 0
    for i, t in enumerate(p):
        if pos[i] == 0:
            compas += 1
        beats.append({"t": round(float(t), 3), "bar": compas, "beat": int(pos[i]) + 1})
    signatura = [6, 8] if compost else [m, 4]
    return {"bpm": round(bpm / 3 if compost else bpm, 1), "time_signature": signatura, "beats": beats}
