"""Alineació d'una tab amb l'àudio: a cada pulsació, quin acord diu la tab.

Les tabs no tenen temps i cadascuna talla les línies i repeteix les seccions a la seva manera, així
que no es comparen directament entre elles: cada tab s'alinea pel seu compte amb l'anàlisi i queda
sobre la graella de pulsacions, on comparar-les és trivial (consens.py).

1. **Paraules**: les subparaules de la lletra de la tab s'aparellen amb les de l'anàlisi
   (`lyrics_align._aparella`, el Needleman-Wunsch de la lletra), així cada paraula de la tab té un
   temps. Si se n'aparellen poques, la tab és d'una altra versió (o d'una altra cançó) i es descarta.
2. **Àncores**: cada acord d'una línia de lletra s'ancora al temps de la síl·laba que té a sota.
3. **Alineació forçada** (programació dinàmica sobre les unitats de pulsació): la tab decideix
   QUIN acord i en quin ordre; l'àudio decideix ON comença exactament (a prop de l'àncora, millor a
   terra o a mig compàs, on l'àudio l'admet millor). Les línies només d'acords (intro, solo) es
   poden repetir senceres; entre seccions de la tab hi pot haver trams sense opinió (instrumentals
   que la tab no escriu); i es pot saltar un acord (amb cost) si la tab en té de més.
4. **Transport**: el que fa coincidir més l'histograma d'acords de la tab amb el de l'àudio (les
   tabs sovint estan en un altre to o amb un capo que no declaren).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from ..notation import NOTES, transposa
from ..stages.lyrics_align import _aparella
from ..text import normalitza
from .model import Tab

MIN_APARELLADES = 0.4  # per sota, la tab no és de la mateixa versió
SUAU = 0.05  # suavitzat de les probabilitats a l'emissió: log(p + SUAU) − log(pmax + SUAU)
TOLERANCIA_ANCORA = 0.75  # pulsacions: la tab posa l'acord una síl·laba amunt o avall
COST_ANCORA = 1.5  # per pulsació més enllà de la tolerància
MAX_COST_ANCORA = 8.0
COST_TEMPS_FEBLE = {1: 0.0, "mig": 0.3, None: 1.0}  # inici d'acord a terra, a mig compàs, o a un altre temps
COST_SALT = 3.0  # saltar-se un acord de la tab
COST_BUIT = 0.8  # per unitat sense opinió (només entre seccions de la tab i als extrems)
COST_BUCLE = 0.5  # tornar a començar una línia només d'acords
PLAUSIBLE = 0.25  # l'acord de la tab és plausible si p ≥ això · pmax (o és entre els 3 primers)
FINESTRA_COMPASSOS = 8
DISTANCIA_SENSE_ANCORA = 8  # pulsacions: més lluny de qualsevol àncora, la posició és poc segura
PES_SENSE_ANCORA = 0.15


@dataclass
class Graella:
    """El que cal de l'anàlisi: unitats de pulsació, probabilitats i paraules amb temps."""
    vores: np.ndarray  # vores de les unitats (U + 1)
    p_unitat: np.ndarray  # U × K
    etiquetes: list[str]  # K (vocabulari de chords_clean, "N" inclòs)
    beats: list[dict]  # {t, bar, beat}
    desfasament: int  # unitat de la primera pulsació
    paraules: list[dict]  # {start, end, text}

    @property
    def n(self) -> int:
        return len(self.p_unitat)


@dataclass
class AcordAlineat:
    idx: int  # índex dins la seqüència d'acords de la tab
    escrit: str  # al to de l'àudio
    k: int  # índex a Graella.etiquetes
    inici: int  # unitat
    fi: int  # unitat (exclosa)
    ancora: float | None  # temps de l'àncora (s)
    linia: int  # índex de LiniaTab
    heretat: bool


@dataclass
class Alineacio:
    tab: Tab
    transport: int  # semitons de les formes escrites al so
    aparellades: float  # fracció de subparaules de la tab aparellades
    acords: list[AcordAlineat]
    k_unitat: np.ndarray  # U: índex d'etiqueta que afirma la tab, o -1
    escrit_unitat: list[str | None]
    pes_unitat: np.ndarray  # U: 0–1, com de segura és la posició
    plausible_unitat: np.ndarray  # U: 1 si l'àudio admet l'acord de la tab, 0 si no, nan sense opinió
    encaix: float  # fracció plausible de les unitats cobertes
    linia_paraula: dict[int, int] = field(default_factory=dict)  # paraula de l'anàlisi → línia de la tab

    def encaix_local(self, finestra: int) -> np.ndarray:
        """Fracció plausible en una finestra centrada a cada unitat (nan si no hi ha opinió)."""
        p = self.plausible_unitat
        valid = ~np.isnan(p)
        nucli = np.ones(finestra)
        suma = np.convolve(np.where(valid, p, 0), nucli, mode="same")
        n = np.convolve(valid.astype(float), nucli, mode="same")
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(n > finestra / 4, suma / np.maximum(n, 1), np.nan)


def index_etiqueta(classe: str, etiquetes: list[str]) -> int | None:
    """Índex de la classe al vocabulari; si no hi és (vocabulari majmin), la més propera."""
    if classe in etiquetes:
        return etiquetes.index(classe)
    m = re.match(r"^([A-G]#?)(.*)$", classe)
    if not m:
        return None
    arrel, q = m.groups()
    for alt in {"m7": ["m"], "m7b5": ["dim", "m"], "dim": ["m"], "7": [""], "maj7": [""]}.get(q, []) + [""]:
        if arrel + alt in etiquetes:
            return etiquetes.index(arrel + alt)
    return None


# 1. Paraules
_RE_TOKEN = re.compile(r"[\w·]+")


def _tokens_linia(text: str) -> list[tuple[int, int, str]]:
    """(columna inicial, columna final, subparaula normalitzada), amb columnes del text original."""
    t = unicodedata.normalize("NFC", text).lower().replace("’", "'")
    if len(t) != len(text):
        t = text.lower()
    return [(m.start(), m.end(), normalitza(m.group(0))[0] if normalitza(m.group(0)) else m.group(0))
            for m in _RE_TOKEN.finditer(t.replace("l.l", "l·l"))]


def _aparella_paraules(tab: Tab, paraules: list[dict]):
    """Temps (inici, fi) de cada subparaula de la tab aparellada, per línia; i el mapa paraula → línia."""
    ref, on = [], []  # on: (línia, columna inicial, columna final)
    for li, l in enumerate(tab.linies):
        for c0, c1, tok in _tokens_linia(l.text):
            ref.append(tok)
            on.append((li, c0, c1))
    hip, de_paraula = [], []
    for wi, w in enumerate(paraules):
        subs = normalitza(w["text"])
        for s_i, s in enumerate(subs):
            hip.append(s)
            d = (w["end"] - w["start"]) / max(len(subs), 1)
            de_paraula.append((wi, w["start"] + d * s_i, w["start"] + d * (s_i + 1)))
    parella = _aparella(ref, hip) if ref and hip else [None] * len(ref)
    per_linia: dict[int, list[tuple[int, int, float, float]]] = {}
    linia_paraula: dict[int, int] = {}
    for (li, c0, c1), j in zip(on, parella):
        if j is not None:
            wi, t0, t1 = de_paraula[j]
            per_linia.setdefault(li, []).append((c0, c1, t0, t1))
            linia_paraula.setdefault(wi, li)
    aparellades = sum(j is not None for j in parella) / max(len(ref), 1)
    return per_linia, linia_paraula, aparellades, len(ref)


def _ancora(col: int, tokens: list[tuple[int, int, float, float]]) -> float | None:
    """Temps de l'acord a la columna `col` d'una línia amb les subparaules aparellades `tokens`."""
    if not tokens:
        return None
    for c0, c1, t0, t1 in tokens:
        if c0 <= col < c1:
            return t0 + (t1 - t0) * (col - c0) / max(c1 - c0, 1)
    seguents = [x for x in tokens if x[0] >= col]
    anteriors = [x for x in tokens if x[1] <= col]
    if seguents and (not anteriors or seguents[0][0] - col <= col - anteriors[-1][1] + 2):
        return seguents[0][2]
    return anteriors[-1][3] if anteriors else None


# 4. Transport
def _histograma(classes: list[tuple[int, bool]], pesos: list[float]) -> np.ndarray:
    h = np.zeros(24)
    for (arrel, menor), w in zip(classes, pesos):
        h[arrel + 12 * menor] += w
    return h / (np.linalg.norm(h) + 1e-9)


def _majmin_etiqueta(e: str) -> tuple[int, bool] | None:
    m = re.match(r"^([A-G]#?)(.*)$", e)
    if not m:
        return None
    q = m.group(2)
    return NOTES.index(m.group(1)), q.startswith(("m", "dim")) and not q.startswith("maj")


def transport(tab: Tab, g: Graella) -> int:
    """Semitons (de les formes escrites) que fan coincidir més la tab amb l'àudio."""
    classes = [_majmin_etiqueta(a.classe) for l in tab.linies for a in l.acords]
    classes = [c for c in classes if c]
    if not classes:
        return tab.transport
    mm = [_majmin_etiqueta(e) for e in g.etiquetes]
    h_audio = np.zeros(24)
    for k, c in enumerate(mm):
        if c:
            h_audio[c[0] + 12 * c[1]] += g.p_unitat[:, k].sum()
    h_audio /= np.linalg.norm(h_audio) + 1e-9
    millor = max(range(12), key=lambda s: (
        float(_histograma([((a + s) % 12, m) for a, m in classes], [1.0] * len(classes)) @ h_audio),
        -min((s - tab.transport) % 12, (tab.transport - s) % 12)))  # empat: el que declara la pàgina
    return millor


# 3. Alineació forçada
def _cost_metric(g: Graella) -> np.ndarray:
    """Cost d'inici d'acord a cada unitat segons la posició al compàs."""
    cost = np.full(g.n, COST_TEMPS_FEBLE[None])
    for b_i, b in enumerate(g.beats):
        u = b_i + g.desfasament
        if u >= g.n:
            break
        if b["beat"] == 1:
            cost[u] = COST_TEMPS_FEBLE[1]
    # Mig compàs: la pulsació a mig camí entre dos inicis de compàs parells
    terres = [i for i, b in enumerate(g.beats) if b["beat"] == 1] + [len(g.beats)]
    for a, b in zip(terres, terres[1:]):
        if (b - a) % 2 == 0 and b - a >= 4:
            u = (a + b) // 2 + g.desfasament
            if u < g.n:
                cost[u] = min(cost[u], COST_TEMPS_FEBLE["mig"])
    return cost


def alinea(tab: Tab, g: Graella) -> Alineacio | None:
    """Alinea la tab amb l'anàlisi. None si la tab no és de la mateixa versió o no té acords."""
    per_linia, linia_paraula, aparellades, n_tokens = _aparella_paraules(tab, g.paraules)
    if n_tokens >= 20 and aparellades < MIN_APARELLADES:
        return None
    semitons = transport(tab, g)
    seq = []  # (línia, escrit, k, àncora, heretat, buit abans)
    sense_acords = False  # hi ha hagut línies de lletra sense acords des de l'últim acord
    for li, l in enumerate(tab.linies):
        if l.text and not l.acords:
            sense_acords = True  # la tab no diu res d'aquesta línia: no vol dir "el mateix acord"
            continue
        for a in sorted(l.acords, key=lambda a: a.col):
            k = index_etiqueta(transposa(a.classe, semitons), g.etiquetes)
            if k is None:
                continue
            anc = _ancora(a.col, per_linia.get(li, [])) if l.text else None
            seq.append((li, transposa(a.escrit, semitons), k, anc, l.heretada, sense_acords))
            sense_acords = False
    if len(seq) < 4:
        return None
    cami = _forcada(seq, tab, g)
    return _resultat(tab, g, seq, cami, semitons, aparellades, linia_paraula)


def _forcada(seq: list, tab: Tab, g: Graella) -> np.ndarray:
    """Estat per unitat: i ≥ 0 = acord i de la seqüència; −1 = sense opinió."""
    n, U = len(seq), g.n
    ks = np.array([s[2] for s in seq])
    ancores = np.array([np.nan if s[3] is None else s[3] for s in seq])
    temps = g.vores[:-1]
    durada_pulsacio = float(np.median(np.diff(g.vores))) if U > 1 else 0.5
    logp = np.log(g.p_unitat + SUAU)
    emissio = logp[:, ks] - np.log(g.p_unitat.max(axis=1) + SUAU)[:, None]  # U × n, ≤ 0
    metric = _cost_metric(g)

    # Buits permesos: abans del primer acord, després de l'últim, i entre seccions de la tab
    linia = [s[0] for s in seq]
    seccio = [tab.linies[li].seccio for li in linia]
    buit_abans = np.zeros(n + 1, dtype=bool)
    buit_abans[0] = buit_abans[n] = True
    for i in range(1, n):
        buit_abans[i] = (seccio[i] != seccio[i - 1] or seq[i][5]
                         or tab.linies[linia[i]].repeticio != tab.linies[linia[i - 1]].repeticio)
    # Bucles: l'últim acord d'una línia només d'acords pot tornar al primer de la mateixa línia
    bucle_de = np.full(n, -1)
    for i in range(n):
        if not tab.linies[linia[i]].text and (i + 1 == n or linia[i + 1] != linia[i]):
            primer = i
            while primer > 0 and linia[primer - 1] == linia[i]:
                primer -= 1
            if primer < i:
                bucle_de[primer] = i  # el primer acord es pot començar des de l'últim

    neg = -1e9
    C = np.full(n, neg)
    G = np.full(n + 1, neg)  # G[i]: sense opinió just abans de l'acord i
    G[0] = -COST_BUIT
    previ_C = np.zeros((U, n), dtype=np.int8)  # 0 queda, 1 avança, 2 salta, 3 des del buit, 4 bucle
    previ_G = np.zeros((U, n + 1), dtype=np.int8)  # 0 queda, 1 des de l'acord anterior
    for u in range(U):
        d = np.abs(temps[u] - ancores) / durada_pulsacio
        c_anc = np.where(np.isnan(d), 0.0, np.minimum(np.maximum(d - TOLERANCIA_ANCORA, 0) * COST_ANCORA,
                                                       MAX_COST_ANCORA))
        inici = -(c_anc + metric[u])
        if u == 0:
            nou_C = np.full(n, neg)
            nou_C[0] = inici[0]
            nou_C[1:] = inici[1:] - COST_SALT * np.arange(1, n)  # començar més endavant a la tab
            pr = np.where(np.arange(n) == 0, 3, 2).astype(np.int8)
            nou_G = G.copy()
            prG = np.zeros(n + 1, dtype=np.int8)
        else:
            opcions = np.full((5, n), neg)
            opcions[0] = C
            opcions[1, 1:] = C[:-1] + inici[1:]
            opcions[2, 2:] = C[:-2] - COST_SALT + inici[2:]
            opcions[3] = np.where(buit_abans[:n], G[:n], neg) + inici
            amb_bucle = bucle_de >= 0
            opcions[4, amb_bucle] = C[bucle_de[amb_bucle]] - COST_BUCLE + inici[amb_bucle]
            pr = opcions.argmax(axis=0).astype(np.int8)
            nou_C = opcions.max(axis=0)
            des_acord = np.full(n + 1, neg)
            des_acord[1:] = np.where(buit_abans[1:], C, neg)
            prG = (des_acord > G).astype(np.int8)
            nou_G = np.maximum(G, des_acord)
        C = nou_C + emissio[u]
        G = nou_G - COST_BUIT
        previ_C[u], previ_G[u] = pr, prG

    # Retrocés
    cami = np.full(U, -1)
    if C[n - 1] >= G[n]:
        estat, i = "C", n - 1
    else:
        estat, i = "G", n
    for u in range(U - 1, -1, -1):
        if estat == "C":
            cami[u] = i
            p = previ_C[u, i]
            if u == 0:
                break
            if p == 1:
                i -= 1
            elif p == 2:
                i -= 2
            elif p == 3:
                estat = "G"
            elif p == 4:
                i = int(bucle_de[i])
        else:
            if previ_G[u, i] == 1:
                estat, i = "C", i - 1
    return cami


def _resultat(tab: Tab, g: Graella, seq: list, cami: np.ndarray, semitons: int, aparellades: float,
              linia_paraula: dict[int, int]) -> Alineacio:
    U = g.n
    k_unitat = np.full(U, -1)
    escrit: list[str | None] = [None] * U
    acords: list[AcordAlineat] = []
    u = 0
    while u < U:
        i = cami[u]
        v = u
        while v < U and cami[v] == i:
            v += 1
        if i >= 0:
            li, e, k, anc, her, _ = seq[i]
            acords.append(AcordAlineat(idx=int(i), escrit=e, k=int(k), inici=u, fi=v, ancora=anc, linia=li,
                                       heretat=her))
            k_unitat[u:v] = k
            escrit[u:v] = [e] * (v - u)
        u = v
    # Pes: 1 als acords ancorats a la lletra; els altres (intros, o una progressió escrita a part
    # que la DP repeteix sobre una estrofa sense acords) decauen de seguida lluny d'una àncora
    pes = np.zeros(U)
    ancorats = [a.inici for a in acords if a.ancora is not None]
    for a in acords:
        dist = min((abs(a.inici - x) for x in ancorats), default=DISTANCIA_SENSE_ANCORA * 2)
        w = 1.0 if a.ancora is not None else max(PES_SENSE_ANCORA, 1.0 - dist / DISTANCIA_SENSE_ANCORA)
        pes[a.inici:a.fi] = w * (0.5 if a.heretat else 1.0)
    # Plausibilitat: l'àudio admet l'acord de la tab
    p = g.p_unitat
    pmax = p.max(axis=1)
    top3 = np.argsort(-p, axis=1)[:, :3]
    plaus = np.full(U, np.nan)
    amb = k_unitat >= 0
    idx = np.where(amb)[0]
    pk = p[idx, k_unitat[idx]]
    plaus[idx] = ((pk >= PLAUSIBLE * pmax[idx]) | (top3[idx] == k_unitat[idx, None]).any(axis=1)).astype(float)
    encaix = float(np.nanmean(plaus)) if amb.any() else 0.0
    return Alineacio(tab=tab, transport=semitons, aparellades=aparellades, acords=acords, k_unitat=k_unitat,
                     escrit_unitat=escrit, pes_unitat=pes, plausible_unitat=plaus, encaix=encaix,
                     linia_paraula=linia_paraula)
