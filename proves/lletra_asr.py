"""Fase 0: transcripció de la veu separada amb faster-whisper.

Ús: python proves/lletra_asr.py <model> <veu.wav> <lletra_ref.txt> <sortida.json>
model: large-v3 | large-v3-turbo | medium ...  (CPU, int8)
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from faster_whisper import WhisperModel  # noqa: E402
from text_util import normalitza, wer  # noqa: E402

nom, veu, ref, sortida = sys.argv[1:5]

t0 = time.perf_counter()
model = WhisperModel(nom, device="cpu", compute_type="int8", cpu_threads=4)
t_carrega = time.perf_counter() - t0

t1 = time.perf_counter()
segments, info = model.transcribe(
    veu, language="ca", word_timestamps=True, vad_filter=True, beam_size=5,
    condition_on_previous_text=False,
)
segments = list(segments)
t_transcripcio = time.perf_counter() - t1

text = "\n".join(s.text.strip() for s in segments)
paraules = [
    {"start": round(w.start, 2), "end": round(w.end, 2), "text": w.word.strip(), "conf": round(w.probability, 2)}
    for s in segments for w in (s.words or [])
]
# WER sobre la lletra de la BD, que no sempre repeteix totes les tornades: és orientatiu
w = wer(normalitza(Path(ref).read_text(encoding="utf-8")), normalitza(text))
resultat = {
    "model": nom, "temps_carrega_s": round(t_carrega, 1), "temps_transcripcio_s": round(t_transcripcio, 1),
    "wer_vs_bd": round(w, 3), "text": text, "paraules": paraules,
}
Path(sortida).write_text(json.dumps(resultat, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{nom}: carrega={t_carrega:.0f}s transcripcio={t_transcripcio:.0f}s WER={w:.2f}")
