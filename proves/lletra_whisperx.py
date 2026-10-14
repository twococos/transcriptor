"""Fase 0: alineació per paraula amb WhisperX + wav2vec2 català (Softcatalà).

Ús: python proves/lletra_whisperx.py <veu.wav> <lletra.lrc> <sortida.json>
Els segments són les línies de l'LRC (inici d'una línia → inici de la següent).
"""

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
import whisperx

MODEL = "softcatala/wav2vec2-large-xlsr-catala"
veu, lrc, sortida = sys.argv[1:4]

audio, sr = sf.read(veu, dtype="float32")
if audio.ndim == 2:
    audio = audio.mean(axis=1)
audio = soxr.resample(audio, sr, 16000).astype(np.float32)
durada = len(audio) / 16000

linies = []
for l in Path(lrc).read_text(encoding="utf-8").splitlines():
    m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", l)
    if m and m.group(3).strip():
        linies.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3).strip()))
segments = [
    {"start": t, "end": linies[i + 1][0] if i + 1 < len(linies) else min(t + 8, durada), "text": text}
    for i, (t, text) in enumerate(linies)
]

t0 = time.perf_counter()
model, meta = whisperx.load_align_model(language_code="ca", device="cpu", model_name=MODEL)
t_carrega = time.perf_counter() - t0

t1 = time.perf_counter()
res = whisperx.align(segments, model, meta, audio, "cpu", return_char_alignments=False)
t_alineacio = time.perf_counter() - t1

paraules = [
    {"start": w.get("start"), "end": w.get("end"), "text": w["word"], "conf": w.get("score")}
    for w in res["word_segments"]
]
sense_temps = sum(1 for p in paraules if p["start"] is None)
Path(sortida).write_text(
    json.dumps({"model": MODEL, "temps_carrega_s": round(t_carrega, 1), "temps_alineacio_s": round(t_alineacio, 1),
                "n_paraules": len(paraules), "sense_temps": sense_temps, "paraules": paraules},
               ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(f"carrega={t_carrega:.0f}s alineacio={t_alineacio:.0f}s paraules={len(paraules)} sense_temps={sense_temps}")
