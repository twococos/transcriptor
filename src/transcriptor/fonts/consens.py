"""Consens entre les tabs i l'àudio: una bonificació per al Viterbi d'acords i la grafia final.

No es fan pedaços sobre el resultat: cada tab alineada (alinea.py) vota a cada pulsació pel seu
acord, amb un pes, i els vots se sumen com a bonificació a les log-probabilitats de BTC abans de
tornar a passar `chords_clean.viterbi_compas`. Així les regles de compàs de la 0.1.13 continuen
valent, l'àudio desempata quan les fonts discrepen, i un acord que l'àudio fa impossible no entra
per molt que el votin (log p molt negatiu).

Pes d'una tab a cada pulsació = prior del lloc × valoració × encaix global amb l'àudio × encaix
local (finestres de 8 compassos: una tab d'una altra versió, o amb un pont equivocat, perd el pes
allà on no encaixa) × àncora (alinea.py: menys pes lluny de la lletra i als acords heretats).

Còpies: dues tabs independents coincideixen en els acords però no en com tallen les línies ni en
la columna exacta de cada acord. Si s'assemblen massa, són la mateixa transcripció copiada d'una
web a una altra i formen un grup que vota com una sola font.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

from .alinea import FINESTRA_COMPASSOS, Alineacio, Graella

PRIOR_LLOC = {"bd": 1.5, "ultimate_guitar": 1.0, "cifraclub": 0.9, "echords": 0.8, "guitartuna": 0.8,
              "lacuerda": 0.7, "acordesweb": 0.7, "acordscatala": 0.6, "text": 1.0}
BO_MANUAL = 1.3  # una tab triada a mà a l'admin
MIN_ENCAIX = 0.45  # per sota, la tab es descarta (una altra versió, un altre to mal detectat…)
ENCAIX_PLE = 0.8  # a partir d'aquí, pes complet
MIN_ENCAIX_LOCAL = 0.3
LLINDAR_COPIA = 0.6  # Jaccard de línies (text + acords a la columna) a partir del qual són còpies
LAMBDA = 1.5  # bonificació (en unitats de log p per pulsació) d'un grup amb pes 1
SEMBLANCA = {"igual": 1.0, "tercera": 0.6, "arrel": 0.3}
MIN_SUPORT_GRAFIA = 0.5  # fracció del pes que ha de dir la mateixa grafia per adoptar-la


@dataclass
class Font:
    al: Alineacio
    pes: float  # pes global (prior × valoració × encaix)
    grup: int = -1
    pes_unitat: np.ndarray = field(default_factory=lambda: np.zeros(0))


@dataclass
class Consens:
    fonts: list[Font]
    bonificacio: np.ndarray  # U × K
    descartades: list[tuple[Alineacio | None, str]]  # (alineació, motiu)
    n_grups: int


def _factor_valoracio(vots: int | None, valoracio: float | None) -> float:
    f = 1.0
    if vots is not None:
        f = 0.8 + 0.2 * min(1.0, math.log10(1 + vots) / 3)  # 1000 vots → 1
    if valoracio and vots and vots >= 5 and valoracio < 4.0:  # sense vots, la valoració és 0
        f *= 0.8
    return f


def _clau_linia(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _empremta(al: Alineacio) -> set:
    """Línies originals de la tab amb els acords a la columna exacta."""
    return {(_clau_linia(l.text), tuple((a.col, a.classe) for a in l.acords))
            for l in al.tab.linies if not l.repeticio and l.acords}


def semblanca_copia(a: Alineacio, b: Alineacio) -> float:
    """Jaccard de les línies amb acords (es comparen les formes escrites, tal com són a la pàgina)."""
    ea, eb = _empremta(a), _empremta(b)
    return len(ea & eb) / max(len(ea | eb), 1)


def _matriu_semblanca(etiquetes: list[str]) -> np.ndarray:
    def parts(e: str):
        m = re.match(r"^([A-G]#?)(.*)$", e)
        if not m:
            return None
        q = m.group(2)
        return m.group(1), q.startswith(("m", "dim")) and not q.startswith("maj")
    K = len(etiquetes)
    S = np.zeros((K, K))
    p = [parts(e) for e in etiquetes]
    for i in range(K):
        for j in range(K):
            if p[i] is None or p[j] is None:
                continue
            if i == j:
                S[i, j] = SEMBLANCA["igual"]
            elif p[i] == p[j]:
                S[i, j] = SEMBLANCA["tercera"]
            elif p[i][0] == p[j][0]:
                S[i, j] = SEMBLANCA["arrel"]
    return S


def calcula(alineacions: list[Alineacio | None], g: Graella, tabs_descartades: list[str] | None = None) -> Consens:
    descartades = [(None, m) for m in tabs_descartades or []]
    fonts: list[Font] = []
    unitats_compas = max(1, round(len(g.beats) / max(1, len({b["bar"] for b in g.beats}))))
    finestra = FINESTRA_COMPASSOS * unitats_compas
    for al in alineacions:
        if al is None:
            continue
        if al.encaix < MIN_ENCAIX:
            descartades.append((al, f"encaix {al.encaix:.0%}"))
            continue
        c = al.tab.crua
        pes = PRIOR_LLOC.get(c.lloc, 0.7) * (BO_MANUAL if c.manual else 1.0) * _factor_valoracio(c.vots, c.valoracio)
        pes *= min(1.0, 0.2 + 0.8 * (al.encaix - MIN_ENCAIX) / (ENCAIX_PLE - MIN_ENCAIX))
        local = al.encaix_local(finestra)
        f_local = np.where(np.isnan(local), 0.0, np.clip((local - MIN_ENCAIX_LOCAL) / 0.4, 0.0, 1.0))
        fonts.append(Font(al=al, pes=pes, pes_unitat=pes * al.pes_unitat * f_local))
    # Grups de còpies (unió-cerca senzilla)
    grup = list(range(len(fonts)))

    def arrel(i: int) -> int:
        while grup[i] != i:
            i = grup[i]
        return i
    for i in range(len(fonts)):
        for j in range(i + 1, len(fonts)):
            if semblanca_copia(fonts[i].al, fonts[j].al) >= LLINDAR_COPIA:
                grup[arrel(j)] = arrel(i)
    grups: dict[int, list[Font]] = {}
    for i, f in enumerate(fonts):
        f.grup = arrel(i)
        grups.setdefault(f.grup, []).append(f)
    # Bonificació: dins d'un grup, els vots es reparteixen perquè el grup pesi com el seu millor membre
    U, K = g.p_unitat.shape
    S = _matriu_semblanca(g.etiquetes)
    bonificacio = np.zeros((U, K))
    for membres in grups.values():
        vots = np.zeros((U, K))
        total = np.zeros(U)
        for f in membres:
            amb = f.al.k_unitat >= 0
            vots[amb] += f.pes_unitat[amb, None] * S[f.al.k_unitat[amb]]
            total += np.where(amb, f.pes_unitat, 0.0)
        maxim = np.max([f.pes_unitat * (f.al.k_unitat >= 0) for f in membres], axis=0)
        escala = np.where(total > 0, maxim / np.maximum(total, 1e-9), 0.0)
        bonificacio += vots * escala[:, None]
    return Consens(fonts=fonts, bonificacio=LAMBDA * bonificacio, descartades=descartades, n_grups=len(grups))


def grafia(segs: list[dict], vores: np.ndarray, cons: Consens, etiquetes: list[str]) -> None:
    """A cada segment que les fonts sostenen, la grafia que hi escriuen (G/B, Cadd9...). Afegeix a
    cada segment `fonts` (pes que vota exactament aquest acord) i deixa l'etiqueta de BTC a `raw`."""
    if not cons.fonts:
        return
    inicis = vores[:-1]
    for s in segs:
        u0 = int(np.searchsorted(inicis, s["start"] - 1e-6))
        u1 = max(u0 + 1, int(np.searchsorted(inicis, s["end"] - 1e-6)))
        k = etiquetes.index(s["raw"]) if s.get("raw") in etiquetes else (
            etiquetes.index(s["label"]) if s["label"] in etiquetes else -1)
        vots: dict[str, float] = {}
        total = 0.0
        a_favor = 0.0
        for f in cons.fonts:
            ku = f.al.k_unitat[u0:u1]
            w = f.pes_unitat[u0:u1]
            total += float(w[ku >= 0].sum())
            for u in range(u0, u1):
                if f.al.k_unitat[u] == k and f.al.escrit_unitat[u]:
                    vots[f.al.escrit_unitat[u]] = vots.get(f.al.escrit_unitat[u], 0.0) + float(f.pes_unitat[u])
                    a_favor += float(f.pes_unitat[u])
        s["fonts"] = round(a_favor / max(u1 - u0, 1), 3)
        s["fonts_total"] = round(total / max(u1 - u0, 1), 3)
        if vots:
            escrit, w = max(vots.items(), key=lambda x: x[1])
            if w >= MIN_SUPORT_GRAFIA * total and escrit != s["label"]:
                s["label"] = escrit
