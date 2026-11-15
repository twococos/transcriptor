"""Rodes d'acords: els compassos d'una zona instrumental que es repeteixen.

La zona es llegeix compàs a compàs. La signatura d'un compàs són els canvis d'acord que hi ha (temps
i classe major/menor: B i B7 compten igual) més l'acord que sona al primer temps, encara que vingui
del compàs anterior. Una roda és un tram de P compassos amb almenys dos acords diferents que es
repeteix seguit, amb les mateixes signatures. Es tria la que cobreix més compassos (en cas d'empat,
la que comença abans i després la més curta: així la roda comença on comença de debò i no a mig
patró) i es torna a buscar al que queda abans i després.

El render escriu la roda una vegada amb "(xN)" (render.linies_compassos).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..notation import majmin

LONGITUDS = (2, 3, 4, 6, 8)  # compassos
MIN_VEGADES = 2

Compas = list[list]  # pulsacions [t, temps del compàs, etiqueta o None]


@dataclass
class Tros:
    compassos: list[Compas]  # una passada (a la roda, l'etiqueta més freqüent de cada temps)
    vegades: int
    originals: list[Compas]  # tots els compassos tal com sonen
    sonant: str | None  # acord que sona just abans del tros


def compassos(pulsacions: list[list]) -> list[Compas]:
    cs: list[Compas] = []
    for p in pulsacions:
        if p[1] == 1 or not cs:
            cs.append([])
        cs[-1].append(list(p))
    return cs


def _classe(etiqueta: str):
    return majmin(etiqueta) or etiqueta


def signatures(cs: list[Compas]) -> tuple[list[tuple], list[str | None]]:
    """(signatura de cada compàs, acord que sona just abans de cada compàs)."""
    sonant: str | None = None
    sig, abans = [], []
    for c in cs:
        abans.append(sonant)
        primer = c[0][2] or sonant
        canvis = [(c[0][1], _classe(primer))] if primer else []
        canvis += [(temps, _classe(et)) for _, temps, et in c[1:] if et]
        sig.append((len(c), c[0][1], tuple(canvis)))
        for _, _, et in c:
            sonant = et or sonant
    return sig, abans


def troba_roda(sig: list[tuple]) -> tuple[int, int, int] | None:
    """(inici, P, vegades) de la roda que cobreix més compassos, o None."""
    millor = None
    n = len(sig)
    for P in LONGITUDS:
        for i in range(n - MIN_VEGADES * P + 1):
            patro = sig[i:i + P]
            if len({cl for s in patro for _, cl in s[2]}) < 2:
                continue
            k = 1
            while i + (k + 1) * P <= n and sig[i + k * P:i + (k + 1) * P] == patro:
                k += 1
            if k >= MIN_VEGADES:
                clau = (k * P, -i, -P)
                if millor is None or clau > millor[0]:
                    millor = (clau, i, P, k)
    return None if millor is None else millor[1:]


def _representant(cs: list[Compas], i: int, P: int, k: int) -> list[Compas]:
    """Una passada de la roda amb l'etiqueta més freqüent a cada temps (B i B7 hi compten igual)."""
    sortida = []
    for j in range(P):
        compas = []
        for q, p in enumerate(cs[i + j]):
            etiquetes = [cs[i + r * P + j][q][2] for r in range(k) if cs[i + r * P + j][q][2]]
            compas.append([p[0], p[1], Counter(etiquetes).most_common(1)[0][0] if etiquetes else None])
        sortida.append(compas)
    return sortida


def _trossos(cs: list[Compas], sig: list[tuple], abans: list[str | None]) -> list[Tros]:
    if not cs:
        return []
    r = troba_roda(sig)
    if r is None:
        return [Tros(compassos=cs, vegades=1, originals=cs, sonant=abans[0])]
    i, P, k = r
    fi = i + k * P
    roda = Tros(compassos=_representant(cs, i, P, k), vegades=k, originals=cs[i:fi], sonant=abans[i])
    return (_trossos(cs[:i], sig[:i], abans[:i]) + [roda] + _trossos(cs[fi:], sig[fi:], abans[fi:]))


def trossos(pulsacions: list[list]) -> list[Tros]:
    """La zona partida en trams sense repetició i rodes (en ordre)."""
    cs = compassos(pulsacions)
    sig, abans = signatures(cs)
    return _trossos(cs, sig, abans)


def _sonen(cs: list[Compas]) -> list[tuple]:
    """Per a cada compàs, la classe major/menor que sona a cada temps."""
    sonant, sortida = None, []
    for c in cs:
        temps = []
        for _, _, et in c:
            sonant = et or sonant
            temps.append(_classe(sonant) if sonant else None)
        sortida.append(tuple(temps))
    return sortida


def _semblanca(a: list[tuple], b: list[tuple]) -> float:
    x = [t for c in a for t in c]
    y = [t for c in b for t in c]
    return sum(p == q for p, q in zip(x, y)) / max(len(x), len(y), 1)


def quasi_rodes(pulsacions: list[list], llindar: float = 0.75) -> list[dict]:
    """Rodes que es repeteixen gairebé iguals (≥ `llindar` dels temps) però no exactament, i per això
    no es comprimeixen. Només per al depurador: [{inici, fi, P, vegades, semblanca}]."""
    cs = compassos(pulsacions)
    sonen = _sonen(cs)
    candidates = []
    for P in LONGITUDS:
        for i in range(len(cs) - MIN_VEGADES * P + 1):
            patro = sonen[i:i + P]
            if len({t for c in patro for t in c if t}) < 2:
                continue
            k, minima = 1, 1.0
            while i + (k + 1) * P <= len(cs):
                s = _semblanca(patro, sonen[i + k * P:i + (k + 1) * P])
                if s < llindar:
                    break
                k, minima = k + 1, min(minima, s)
            if k >= MIN_VEGADES and minima < 1.0:
                candidates.append((k * P, -i, -P, i, P, k, minima))
    triades, ocupat = [], set()
    for _, _, _, i, P, k, minima in sorted(candidates, reverse=True):
        rang = set(range(i, i + k * P))
        if rang & ocupat:
            continue
        ocupat |= rang
        fi = cs[i + k * P][0][0] if i + k * P < len(cs) else cs[-1][-1][0]
        triades.append({"inici": cs[i][0][0], "fi": fi, "P": P, "vegades": k, "semblanca": round(minima, 3)})
    return sorted(triades, key=lambda r: r["inici"])
