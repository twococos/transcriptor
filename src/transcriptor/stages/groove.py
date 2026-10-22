"""Etapa groove: empremta rítmica de l'acompanyament, per triar l'estil (postprocess/style.py).

L'acompanyament és la mescla menys la veu separada (serveix igual amb htdemucs que amb roformer).
Se'n treu l'envolupant d'atacs (onset strength) en tres bandes:
  - greus  (< 150 Hz):      baix i bombo
  - mitjos (150 Hz - 2 kHz): guitarra, piano, caixa
  - aguts  (> 2 kHz):       fregament del rasgueig, charles, shaker

Cada temps del compàs es parteix en franges (4 en compassos simples; 2 en 6/8, on el temps ja és una
corxera) i, per a cada franja, es pren l'atac més fort al seu voltant. La mitjana per posició sobre
tots els compassos complets és l'empremta: una fila de compàs per banda (16 franges en 4/4, 12 en
3/4 i en 6/8), normalitzada a 0-1. S'hi afegeixen mesures globals: swing, regularitat del tempo,
densitat d'atacs i com de "pla" és l'espectre als atacs (un rasgueig és soroll de banda ampla; un
arpegi, notes netes).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..audio import llegeix

log = logging.getLogger(__name__)

SR = 22050
HOP = 256
N_MELS = 64
TALL_GREUS = 150.0
TALL_AGUTS = 2000.0
MIN_COMPASSOS = 4
VERSIO = 2


def es_compost(time_signature: tuple[int, int] | list[int]) -> bool:
    n, d = time_signature
    return d == 8 and n >= 6 and n % 3 == 0


def _envolupants(acomp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Atacs per banda (3, trames) i planor espectral per trama."""
    import librosa

    S = librosa.feature.melspectrogram(y=acomp, sr=SR, n_fft=2048, hop_length=HOP, n_mels=N_MELS, fmax=SR / 2)
    S_db = librosa.power_to_db(S, ref=np.max)
    freqs = librosa.mel_frequencies(n_mels=N_MELS, fmax=SR / 2)
    i_greus = int(np.searchsorted(freqs, TALL_GREUS))
    i_aguts = int(np.searchsorted(freqs, TALL_AGUTS))
    env = librosa.onset.onset_strength_multi(S=S_db, sr=SR, hop_length=HOP,
                                             channels=[0, max(i_greus, 1), i_aguts, N_MELS])
    planor = librosa.feature.spectral_flatness(y=acomp, n_fft=2048, hop_length=HOP)[0]
    n = min(env.shape[1], len(planor))
    return env[:, :n], planor[:n]


def _compassos(beats: list[dict], numerador: int) -> list[list[float]]:
    """Temps de cada compàs complet: les `numerador`+1 vores (l'últim temps i el següent primer)."""
    out = []
    for i, b in enumerate(beats):
        if b["beat"] != 1 or i + numerador >= len(beats):
            continue
        tros = beats[i: i + numerador + 1]
        if [x["beat"] for x in tros[:-1]] == list(range(1, numerador + 1)) and tros[-1]["beat"] == 1:
            out.append([x["t"] for x in tros])
    return out


def _pic(env: np.ndarray, t: float, mig: float) -> float:
    """Màxim de l'envolupant al voltant de `t` (± `mig` s)."""
    a = max(int((t - mig) * SR / HOP), 0)
    b = min(int(np.ceil((t + mig) * SR / HOP)) + 1, len(env))
    return float(env[a:b].max()) if b > a else 0.0


def calcula(mescla: np.ndarray, veu: np.ndarray, beats: list[dict], time_signature) -> dict | None:
    """Empremta a partir de senyals mono a SR. None si no hi ha prou compassos complets."""
    n = min(len(mescla), len(veu))
    acomp = (mescla[:n] - veu[:n]).astype(np.float32)
    numerador = int(time_signature[0])
    compost = es_compost(time_signature)
    franges = 2 if compost else 4
    compassos = _compassos(beats, numerador)
    if len(compassos) < MIN_COMPASSOS:
        return None

    env, planor = _envolupants(acomp)
    per_compas = numerador * franges
    matrius = np.zeros((3, len(compassos), per_compas), dtype=np.float32)
    swing_mig, swing_terc, swing_quart = [], [], []
    for c, vores in enumerate(compassos):
        for k in range(numerador):
            t0, t1 = vores[k], vores[k + 1]
            dur = t1 - t0
            mig = max(min(0.035, dur / franges * 0.4), 0.01)
            for s in range(franges):
                t = t0 + dur * s / franges
                for banda in range(3):
                    matrius[banda, c, k * franges + s] = _pic(env[banda], t, mig)
            if not compost:
                # Swing: la corxera de després cau a 1/2 (recte) o a 2/3 (de tresets) del temps. Les
                # semicorxeres (3/4) també cauen a prop del 2/3: es comparen totes tres
                for banda in (1, 2):
                    swing_mig.append(_pic(env[banda], t0 + dur / 2, 0.012))
                    swing_terc.append(_pic(env[banda], t0 + dur * 2 / 3, 0.012))
                    swing_quart.append(_pic(env[banda], t0 + dur * 3 / 4, 0.012))

    # Accents relatius dins de cada compàs, i mediana entre compassos (robusta als canvis de secció)
    perfils = []
    for banda in range(3):
        m = matrius[banda]
        m = m / (m.mean(axis=1, keepdims=True) + 1e-6)
        p = np.median(m, axis=0)
        p = p / (p.max() + 1e-6)
        perfils.append(p)

    # Densitat: part de les franges amb un atac clar (banda mitja, relatiu al compàs)
    mitja = matrius[1] / (matrius[1].max(axis=1, keepdims=True) + 1e-6)
    densitat = float((mitja > 0.5).mean())

    # Planor espectral als atacs forts de la banda mitja
    pics = env[1]
    llindar = np.quantile(pics, 0.9)
    trames = np.where(pics >= llindar)[0]
    planor_atacs = float(np.median(planor[trames])) if len(trames) else 0.0

    # Irregularitat del tempo: desviació absoluta mediana dels intervals entre temps, relativa a la
    # mediana. Robusta als forats del detector (un temps perdut no la dispara); una cançó a tempo
    # lliure (rubato) dona valors alts.
    intervals = np.diff([b["t"] for b in beats])
    intervals = intervals[intervals > 0]
    if len(intervals) > 2:
        med = float(np.median(intervals))
        regularitat = float(np.median(np.abs(intervals - med)) / med)
    else:
        regularitat = 1.0

    swing = None
    if swing_mig:
        # Part de l'energia dels contratemps que cau al treset: ~0,33 recte, ~0,5 o més amb swing
        a, b, c = float(np.mean(swing_mig)), float(np.mean(swing_terc)), float(np.mean(swing_quart))
        swing = b / (a + b + c + 1e-6)

    return {
        "versio": VERSIO,
        "slots_per_beat": franges,
        "beats_per_bar": numerador,
        "low": [round(float(x), 3) for x in perfils[0]],
        "mid": [round(float(x), 3) for x in perfils[1]],
        "high": [round(float(x), 3) for x in perfils[2]],
        "compassos": len(compassos),
        "densitat": round(densitat, 3),
        "planor": round(planor_atacs, 4),
        "swing": round(swing, 3) if swing is not None else None,
        "regularitat": round(regularitat, 4),
    }


def empremta(cami_mescla: Path, cami_veu: Path, beats: list[dict], time_signature) -> dict | None:
    mescla, _ = llegeix(cami_mescla, sr=SR, mono=True)
    veu, _ = llegeix(cami_veu, sr=SR, mono=True)
    return calcula(mescla, veu, beats, time_signature)
