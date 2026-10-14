"""Fase 0: avalua l'alineació de paraules contra els inicis de línia d'un LRC.

Ús: python proves/avalua_alineacio.py <lletra.lrc> <alineacio.json>...
Per a cada línia de l'LRC, busca la paraula alineada on comença la línia (per posició de lletres,
independent de com cada eina parteixi les paraules) i en compara l'inici amb el temps de l'LRC.
"""

import json
import re
import sys
from pathlib import Path

import numpy as np


def lletres(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalpha())


linies = []
for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", l)
    if m and lletres(m.group(3)):
        linies.append((int(m.group(1)) * 60 + float(m.group(2)), lletres(m.group(3))))

for fitxer in sys.argv[2:]:
    paraules = json.loads(Path(fitxer).read_text(encoding="utf-8"))["paraules"]
    # Offset de lletres on comença cada paraula alineada
    inicis, offset = [], 0
    for p in paraules:
        inicis.append((offset, p["start"]))
        offset += len(lletres(p["text"]))
    errors, offset_linia = [], 0
    for t_lrc, text in linies:
        candidats = [s for o, s in inicis if o >= offset_linia and s is not None]
        if candidats:
            errors.append(candidats[0] - t_lrc)
        offset_linia += len(text)
    errors = np.array(errors)
    e = np.abs(errors)
    # Els LRC poden anar desplaçats respecte del vídeo: també mesurem amb el desplaçament restat
    e_corr = np.abs(errors - np.median(errors))
    print(
        f"{Path(fitxer).stem}: línies={len(e)} error mediana={np.median(e):.2f}s "
        f"<0,5s={np.mean(e < 0.5):.0%} <1s={np.mean(e < 1):.0%} màx={e.max():.1f}s "
        f"(desplaçament mediana {np.median(errors):+.2f}s → corregit: mediana={np.median(e_corr):.2f}s "
        f"<0,5s={np.mean(e_corr < 0.5):.0%} <1s={np.mean(e_corr < 1):.0%})"
    )
