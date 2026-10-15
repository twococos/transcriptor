"""Diagnòstic: desfasament (en paraules) entre on posem cada acord i on el posa la BD.

Ús: python proves/desfas_paraules.py <dir_resultats_bench>
Per a cada línia de lletra comuna, aparella els acords de la referència i els predits per ordre
(mateix acord majmin, aplicant el transport) i compta la diferència d'índex de paraula.
"""

import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from transcriptor.bench.metrics import _index_paraula, llegeix_content  # noqa: E402
from transcriptor.notation import majmin  # noqa: E402
from transcriptor.text import normalitza  # noqa: E402

dir_res = Path(sys.argv[1])
transport = {int(f["id"]): int(f["transport"]) for f in csv.DictReader(open(dir_res / "resultats.csv", encoding="utf-8"))
             if f.get("transport")}
hist = collections.Counter()
for d in sorted(p for p in dir_res.iterdir() if p.is_dir()):
    tr = transport.get(int(d.name), 0)
    ref = [l for l in llegeix_content((d / "referencia.txt").read_text(encoding="utf-8")) if l["tipus"] == "lletra"]
    pred = [l for l in llegeix_content((d / "content.txt").read_text(encoding="utf-8")) if l["tipus"] == "lletra"]
    claus = [" ".join(normalitza(l["text"])) for l in pred]
    j = 0
    for l in ref:
        try:
            k = claus.index(" ".join(normalitza(l["text"])), j)
        except ValueError:
            continue
        j = k + 1
        p_acords = [(_index_paraula(pred[k]["text"], pos), majmin(a)) for pos, a in pred[k]["acords"]]
        for pos, a in l["acords"]:
            mm = majmin(a)
            if not mm:
                continue
            esperat = ((mm[0] + tr) % 12, mm[1])
            iw = _index_paraula(l["text"], pos)
            cands = [pw for pw, pa in p_acords if pa == esperat]
            if not cands:
                hist["sense acord igual a la línia"] += 1
                continue
            hist[min(cands, key=lambda pw: abs(pw - iw)) - iw] += 1
total = sum(hist.values())
for k, v in sorted(hist.items(), key=lambda x: (isinstance(x[0], str), x[0])):
    print(f"{k!s:>30}: {v:4d} ({100 * v / total:.0f} %)")
