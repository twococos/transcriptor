"""Fase 0: recalcula el WER de les transcripcions contra la lletra realment cantada.

Ús: python proves/wer.py <lletra_cantada.txt> <resultat.json>...
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from text_util import normalitza, wer  # noqa: E402

ref = normalitza(Path(sys.argv[1]).read_text(encoding="utf-8"))
for fitxer in sys.argv[2:]:
    d = json.loads(Path(fitxer).read_text(encoding="utf-8"))
    print(f"{Path(fitxer).stem}: WER={wer(ref, normalitza(d['text'])):.3f} (ref {len(ref)} paraules)")
