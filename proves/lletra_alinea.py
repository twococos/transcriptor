"""Fase 0: alineació forçada de la lletra coneguda amb stable-ts.

Ús: python proves/lletra_alinea.py <model> <veu.wav> <lletra.txt> <sortida.json>
model: "fw:large-v3-turbo" (faster-whisper) o "medium" (Whisper d'OpenAI)
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
import stable_whisper

nom, veu, lletra, sortida = sys.argv[1:5]

t0 = time.perf_counter()
# "fw:<model>" → backend faster-whisper (CTranslate2, int8); si no, Whisper d'OpenAI (PyTorch)
if nom.startswith("fw:"):
    model = stable_whisper.load_faster_whisper(nom[3:], device="cpu", compute_type="int8", cpu_threads=4)
else:
    model = stable_whisper.load_model(nom, device="cpu")
t_carrega = time.perf_counter() - t0

text = Path(lletra).read_text(encoding="utf-8")
# Carreguem l'àudio nosaltres (16 kHz mono) per no dependre de l'executable ffmpeg al PATH
audio, sr = sf.read(veu, dtype="float32")
audio = soxr.resample(audio.mean(axis=1) if audio.ndim == 2 else audio, sr, 16000).astype(np.float32)
t1 = time.perf_counter()
res = model.align(audio, text, language="ca")
t_alineacio = time.perf_counter() - t1

paraules = [
    {"start": round(w.start, 2), "end": round(w.end, 2), "text": w.word.strip(), "conf": round(w.probability or 0, 2)}
    for w in res.all_words()
]
resultat = {
    "model": nom, "temps_carrega_s": round(t_carrega, 1), "temps_alineacio_s": round(t_alineacio, 1),
    "n_paraules": len(paraules), "paraules": paraules,
}
Path(sortida).write_text(json.dumps(resultat, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{nom}: carrega={t_carrega:.0f}s alineacio={t_alineacio:.0f}s paraules={len(paraules)}")
