"""Estil rítmic de l'acompanyament a partir de l'empremta de groove (stages/groove.py).

Els IDs són contracte amb el canconer (src/lib/player/styles.ts: el reproductor hi tria el patró de
guitarra) i amb docs/api_worker.md: no se'n reanomena cap.

Primera versió sense entrenar: cada estil té una o més plantilles d'accents per banda (greus, mitjos,
aguts) dins el compàs, un compàs admès i un tempo habitual. La puntuació combina la correlació de
l'empremta amb la plantilla (per banda), el tempo i el swing. Les probabilitats surten d'un softmax
de les puntuacions; la confiança és la del guanyador. Amb el tempo molt irregular (rubato), `lliure`.

Les plantilles es llegeixen com a cadenes d'accents 0-9, una xifra per franja: 16 franges en 4/4
(semicorxeres), 12 en 3/4 (semicorxeres) i 12 en 6/8 (dues per corxera).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

STYLE_IDS = (
    "pop", "balada", "rock", "folk", "rumba", "havanera", "marxa", "reggae", "bossa", "swing",
    "vals", "vals-arpegi", "compost-arpegi", "compost-rasgueig", "lliure",
)

# Per sobre d'aquesta irregularitat del tempo (MAD relativa dels intervals), la cançó és a tempo lliure
IRREGULAR = 0.15
TEMPERATURA = 0.12
PES_BANDES = (0.8, 1.2, 0.6)  # greus, mitjos, aguts


@dataclass
class Plantilla:
    low: str
    mid: str
    high: str


@dataclass
class Estil:
    id: str
    metre: str  # "simple4" (4/4, 2/4, 2/2), "simple3" (3/4) o "compost" (6/8, 12/8)
    bpm: tuple[float, float]  # tempo de la pulsació (en 6/8, la negra amb punt)
    plantilles: list[Plantilla] = field(default_factory=list)
    swing: bool = False
    # Freqüència a priori (puntuació que se suma): els estils rars necessiten més evidència
    previ: float = 0.0


ESTILS: list[Estil] = [
    Estil("pop", "simple4", (80, 140), [
        Plantilla(low="9000003080000300", mid="6050905060509050", high="6060806060608060"),
    ], previ=0.15),
    Estil("balada", "simple4", (50, 90), [
        Plantilla(low="9000000060000000", mid="7060606070606060", high="3030303030303030"),
        Plantilla(low="9000000070000000", mid="5000700050007000", high="2020202020202020"),
    ]),
    Estil("rock", "simple4", (110, 190), [
        Plantilla(low="9070707090707070", mid="7070907070709070", high="8080808080808080"),
    ]),
    Estil("folk", "simple4", (80, 150), [
        Plantilla(low="9000000080000000", mid="2000905020009050", high="2000704020007040"),
    ]),
    Estil("rumba", "simple4", (85, 150), [
        Plantilla(low="9000007080000070", mid="5066906650669066", high="6666966666669666"),
        # Baix en tresillo (3+3+2) i cop al 2 i al 4
        Plantilla(low="9008008090080080", mid="5056905650569056", high="6666966666669666"),
    ], previ=0.05),
    Estil("havanera", "simple4", (50, 85), [
        Plantilla(low="9008906090089060", mid="8008806080088060", high="3003303030033030"),
    ], previ=-0.15),
    Estil("marxa", "simple4", (95, 150), [
        Plantilla(low="9000500090005000", mid="2000900020009000", high="5050905050509050"),
    ], previ=-0.15),
    Estil("reggae", "simple4", (60, 180), [
        # One drop (tempo lent): bombo al tercer temps, skank al 2 i al 4
        Plantilla(low="1000000090000000", mid="1000900010009000", high="5050505050505050"),
        # Ska: skank a cada contratemps
        Plantilla(low="8000800080008000", mid="1090109010901090", high="3090309030903090"),
    ], previ=0.05),
    Estil("bossa", "simple4", (100, 160), [
        Plantilla(low="9000007080000070", mid="8008007000807000", high="5050505050505050"),
    ], previ=-0.1),
    Estil("swing", "simple4", (90, 200), [
        Plantilla(low="9000000080000000", mid="3000900030009000", high="7000700070007000"),
    ], swing=True, previ=-0.2),
    Estil("vals", "simple3", (90, 210), [
        Plantilla(low="900000000000", mid="200090009000", high="200070007000"),
    ]),
    Estil("vals-arpegi", "simple3", (60, 140), [
        Plantilla(low="900000000000", mid="706060606060", high="303030303030"),
    ]),
    Estil("compost-arpegi", "compost", (35, 75), [
        Plantilla(low="900000600000", mid="807070807070", high="303030303030"),
    ]),
    Estil("compost-rasgueig", "compost", (50, 110), [
        Plantilla(low="900000800000", mid="905070905070", high="707070707070"),
    ]),
]


def metre(time_signature) -> str:
    n, d = int(time_signature[0]), int(time_signature[1])
    if d == 8 and n >= 6 and n % 3 == 0:
        return "compost"
    if n == 3:
        return "simple3"
    return "simple4"


def _vector(cadena: str) -> np.ndarray:
    return np.array([int(c) for c in cadena], dtype=np.float64) / 9


def _ajusta(perfil: list[float], n: int) -> np.ndarray:
    """Perfil mesurat a `n` franges (un 2/4 contra una plantilla de 4/4 es repeteix)."""
    v = np.asarray(perfil, dtype=np.float64)
    if len(v) == n:
        return v
    if len(v) and n % len(v) == 0:
        return np.tile(v, n // len(v))
    # Altres casos (compassos irregulars): reinterpolació
    x = np.linspace(0, 1, len(v), endpoint=False)
    return np.interp(np.linspace(0, 1, n, endpoint=False), x, v, period=1)


def _correlacio(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-9 else 0.0


def _previ_tempo(bpm: float, rang: tuple[float, float]) -> float:
    """0 dins el rang; negatiu fora, en octaves. També prova el doble i la meitat (el detector de
    temps de vegades compta corxeres o blanques), amb una petita penalització."""
    millor = -math.inf
    for factor, penal in ((1, 0.0), (0.5, 0.1), (2, 0.1)):
        t = bpm * factor
        if rang[0] <= t <= rang[1]:
            d = 0.0
        else:
            vora = rang[0] if t < rang[0] else rang[1]
            d = abs(math.log2(t / vora))
        millor = max(millor, -0.8 * d - penal)
    return millor


def puntuacions(empremta: dict, bpm: float, time_signature) -> dict[str, float]:
    m = metre(time_signature)
    sw = empremta.get("swing")
    out: dict[str, float] = {}
    for e in ESTILS:
        if e.metre != m:
            continue
        millor = -math.inf
        for p in e.plantilles:
            s = 0.0
            for pes, banda, cadena in zip(PES_BANDES, ("low", "mid", "high"), (p.low, p.mid, p.high)):
                t = _vector(cadena)
                s += pes * _correlacio(_ajusta(empremta[banda], len(t)), t)
            millor = max(millor, s / sum(PES_BANDES))
        millor += _previ_tempo(bpm, e.bpm) + e.previ
        if sw is not None:
            # ~0,33 recte, ~0,5 o més amb swing (vegeu groove.py)
            if e.swing:
                millor += 0.6 * float(np.clip((sw - 0.45) / 0.1, -1, 1))
            else:
                millor -= 0.3 * float(np.clip((sw - 0.5) / 0.1, 0, 1))
        out[e.id] = millor
    return out


def classifica(empremta: dict | None, bpm: float | None, time_signature) -> dict:
    """{"style", "confidence", "alternatives": [[id, prob], ...]} (el contracte del camp `rhythm`)."""
    if not empremta or bpm is None:
        return {"style": "lliure", "confidence": 0.5, "alternatives": []}
    if empremta.get("regularitat", 0) > IRREGULAR:
        conf = float(np.clip(0.5 + (empremta["regularitat"] - IRREGULAR) * 5, 0.5, 0.95))
        return {"style": "lliure", "confidence": round(conf, 3), "alternatives": []}
    s = puntuacions(empremta, bpm, time_signature)
    if not s:
        return {"style": "lliure", "confidence": 0.5, "alternatives": []}
    ids = list(s)
    v = np.array([s[i] for i in ids]) / TEMPERATURA
    p = np.exp(v - v.max())
    p /= p.sum()
    ordre = np.argsort(-p)
    return {
        "style": ids[ordre[0]],
        "confidence": round(float(p[ordre[0]]), 3),
        "alternatives": [[ids[k], round(float(p[k]), 3)] for k in ordre[1:4]],
    }
