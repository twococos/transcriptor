"""Fase 0: prova de Beat This! sobre una cançó.

Ús: python proves/ritme_beatthis.py <àudio.wav> <sortida.json>
Desa pulsacions, inicis de compàs, tempo i compàs estimats.
"""

import json
import sys
import time
from collections import Counter

import numpy as np
import soundfile as sf
from beat_this.inference import Audio2Beats

entrada, sortida = sys.argv[1], sys.argv[2]

t0 = time.perf_counter()
model = Audio2Beats(checkpoint_path="final0", device="cpu")
t_carrega = time.perf_counter() - t0

senyal, sr = sf.read(entrada, dtype="float64")
if senyal.ndim == 2:
    senyal = senyal.mean(axis=1)
t1 = time.perf_counter()
pulsacions, inicis_compas = model(senyal, sr)
t_inferencia = time.perf_counter() - t1

# Tempo: mediana dels intervals entre pulsacions
bpm = 60.0 / float(np.median(np.diff(pulsacions)))
# Compàs: moda de pulsacions entre inicis de compàs consecutius
per_compas = [
    int(((pulsacions >= a) & (pulsacions < b)).sum())
    for a, b in zip(inicis_compas[:-1], inicis_compas[1:])
]
compas = Counter(per_compas).most_common(3)

resultat = {
    "temps_carrega_s": round(t_carrega, 2),
    "temps_inferencia_s": round(t_inferencia, 2),
    "durada_s": round(len(senyal) / sr, 1),
    "bpm": round(bpm, 1),
    "pulsacions_per_compas": compas,
    "n_pulsacions": len(pulsacions),
    "n_compassos": len(inicis_compas),
    "primer_inici_compas": round(float(inicis_compas[0]), 2) if len(inicis_compas) else None,
    "pulsacions": [round(float(x), 3) for x in pulsacions],
    "inicis_compas": [round(float(x), 3) for x in inicis_compas],
}
with open(sortida, "w", encoding="utf-8") as f:
    json.dump(resultat, f, ensure_ascii=False)
print({k: v for k, v in resultat.items() if k not in ("pulsacions", "inicis_compas")})
