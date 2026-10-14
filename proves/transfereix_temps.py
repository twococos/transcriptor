"""Fase 0: temps per paraula de la lletra coneguda a partir de l'ASR, sense model d'alineació.

Ús: python proves/transfereix_temps.py <lletra.txt> <asr.json> <sortida.json>
Alinea les paraules de la lletra amb les de l'ASR (Needleman-Wunsch, coincidència aproximada per
similitud de caràcters), copia els temps de les parelles i interpola les paraules no aparellades.
"""

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from text_util import normalitza  # noqa: E402

lletra, asr, sortida = sys.argv[1:4]
ref = normalitza(Path(lletra).read_text(encoding="utf-8"))
paraules_asr = []
for p in json.loads(Path(asr).read_text(encoding="utf-8"))["paraules"]:
    for w in normalitza(p["text"]):  # l'ASR pot partir "L'avi" en "L" + "'avi"
        paraules_asr.append((w, p["start"], p["end"]))
hip = [w for w, _, _ in paraules_asr]


def similitud(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# Needleman-Wunsch: aparellar si similitud >= 0,6 (+2·sim), forat -0,5
n, m = len(ref), len(hip)
P = [[0.0] * (m + 1) for _ in range(n + 1)]
D = [[""] * (m + 1) for _ in range(n + 1)]
for i in range(1, n + 1):
    P[i][0], D[i][0] = -0.5 * i, "u"
for j in range(1, m + 1):
    P[0][j], D[0][j] = -0.5 * j, "l"
for i in range(1, n + 1):
    for j in range(1, m + 1):
        s = similitud(ref[i - 1], hip[j - 1])
        diag = P[i - 1][j - 1] + (2 * s if s >= 0.6 else -1)
        P[i][j], D[i][j] = max((diag, "d"), (P[i - 1][j] - 0.5, "u"), (P[i][j - 1] - 0.5, "l"))
temps = [None] * n
i, j = n, m
while i > 0 and j > 0:
    if D[i][j] == "d":
        if similitud(ref[i - 1], hip[j - 1]) >= 0.6:
            temps[i - 1] = paraules_asr[j - 1][1:]
        i, j = i - 1, j - 1
    elif D[i][j] == "u":
        i -= 1
    else:
        j -= 1

# Interpolació lineal per a les paraules sense parella
aparellades = sum(t is not None for t in temps)
coneguts = [k for k, t in enumerate(temps) if t is not None]
for k in range(n):
    if temps[k] is None:
        ant = max((c for c in coneguts if c < k), default=None)
        seg = min((c for c in coneguts if c > k), default=None)
        if ant is not None and seg is not None:
            t = temps[ant][1] + (temps[seg][0] - temps[ant][1]) * (k - ant) / (seg - ant)
        else:
            t = temps[ant][1] if ant is not None else temps[seg][0]
        temps[k] = (t, t)
resultat = {
    "aparellades": aparellades, "total": n,
    "paraules": [{"start": round(a, 2), "end": round(b, 2), "text": w} for w, (a, b) in zip(ref, temps)],
}
Path(sortida).write_text(json.dumps(resultat, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{Path(sortida).stem}: {aparellades}/{n} paraules aparellades amb l'ASR")
