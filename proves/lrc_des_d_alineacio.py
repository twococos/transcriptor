"""Fase 0: genera un LRC (inici de cada línia) a partir d'una alineació per paraules.

Ús: python proves/lrc_des_d_alineacio.py <lletra.txt> <alineacio.json> <sortida.lrc>
"""

import json
import sys
from pathlib import Path


def lletres(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalpha())


linies = [l for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if lletres(l)]
paraules = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["paraules"]
inicis, offset = [], 0
for p in paraules:
    inicis.append((offset, p["start"]))
    offset += len(lletres(p["text"]))

sortida, offset = [], 0
for l in linies:
    t = next(s for o, s in inicis if o >= offset)
    sortida.append(f"[{int(t // 60):02d}:{t % 60:05.2f}] {l}")
    offset += len(lletres(l))
Path(sys.argv[3]).write_text("\n".join(sortida) + "\n", encoding="utf-8")
