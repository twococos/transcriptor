"""Fase 0: mesura indirecta de la qualitat de separació.

Ús: python proves/fuita_veu.py <paraules.json> <veu.wav>...
Calcula l'energia de la pista de veu fora dels trams cantats (segons els temps de paraula de l'ASR,
amb marge d'1 s) respecte de la de dins, en dB. Més negatiu = menys fuita d'instruments a la veu.
"""

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

paraules = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["paraules"]
for fitxer in sys.argv[2:]:
    audio, sr = sf.read(fitxer, dtype="float32")
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    cantat = np.zeros(len(audio), dtype=bool)
    for p in paraules:
        a, b = int(max(p["start"] - 1, 0) * sr), int((p["end"] + 1) * sr)
        cantat[a:b] = True
    rms = lambda x: float(np.sqrt(np.mean(x**2)) + 1e-12)  # noqa: E731
    db = 20 * np.log10(rms(audio[~cantat]) / rms(audio[cantat]))
    print(f"{fitxer}: fora/dins = {db:.1f} dB (fora: {(~cantat).sum() / sr:.0f} s)")
