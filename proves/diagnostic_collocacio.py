"""Diagnòstic de col·locació: on cau, en temps, cada acord de la BD respecte de la paraula on el posa.

Ús: python proves/diagnostic_collocacio.py <dir_resultats_bench>
Per a cada línia de lletra de la referència que també és a la sortida (mateix text), i per a cada
acord de la referència, busca a l'anàlisi el canvi d'acord (mateixa arrel/mode, amb el transport
detectat) més proper a l'inici de la paraula on la BD el col·loca, i mesura
Δ = t_canvi − inici_paraula. Si Δ és sistemàticament positiu, col·loquem els acords tard.
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from transcriptor.bench.metrics import _index_paraula, llegeix_content  # noqa: E402
from transcriptor.notation import majmin  # noqa: E402
from transcriptor.text import normalitza  # noqa: E402

deltes, rel_beat = [], []
for d in sorted(Path(sys.argv[1]).iterdir()):
    if not (d / "analysis.json").exists():
        continue
    an = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
    ref = [l for l in llegeix_content((d / "referencia.txt").read_text(encoding="utf-8")) if l["tipus"] == "lletra"]
    paraules = an["words"]
    linies = an["lines"]
    claus_pred = [" ".join(normalitza(" ".join(w["text"] for w in paraules[a:b]))) for a, b in
                  (l["word_range"] for l in linies)]
    canvis = [(c["start"], majmin(c["label"])) for c in an["chords"]]
    ibi = float(np.median(np.diff([b["t"] for b in an["beats"]]))) if len(an["beats"]) > 1 else 0.5
    j = 0
    for l in ref:
        clau = " ".join(normalitza(l["text"]))
        try:
            k = claus_pred.index(clau, j)
        except ValueError:
            continue
        j = k + 1
        a, b = linies[k]["word_range"]
        for pos, acord in l["acords"]:
            idx = _index_paraula(l["text"], pos)
            if a + idx >= b:
                continue
            t_paraula = paraules[a + idx]["start"]
            mm = majmin(acord)
            candidats = [t for t, c in canvis if c and mm and c[1] == mm[1] and abs(t - t_paraula) < 4]
            if candidats:
                t = min(candidats, key=lambda x: abs(x - t_paraula))
                deltes.append(t - t_paraula)
                rel_beat.append((t - t_paraula) / ibi)

d = np.array(deltes)
print(f"{len(d)} acords; Δ (s): mediana {np.median(d):+.2f}, p25 {np.percentile(d, 25):+.2f}, "
      f"p75 {np.percentile(d, 75):+.2f}; |Δ|<0,25 s: {np.mean(np.abs(d) < 0.25):.0%}")
rb = np.array(rel_beat)
print(f"Δ en pulsacions: mediana {np.median(rb):+.2f}, p25 {np.percentile(rb, 25):+.2f}, p75 {np.percentile(rb, 75):+.2f}")
hist, vores = np.histogram(d, bins=np.arange(-2, 2.01, 0.25))
for h, v in zip(hist, vores):
    print(f"{v:+.2f} {'#' * int(h)}")
