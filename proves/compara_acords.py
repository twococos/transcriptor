"""Fase 0: compara els acords predits (.lab) amb els de la BD.

Ús: python proves/compara_acords.py <ref.json> <pred.lab> [min_durada_s]
- Referència: acords del content en ordre, col·lapsant repeticions consecutives.
- Predicció: segments del .lab sense "N", descartant els més curts que min_durada_s.
- Tot a nivell majmin. Alineament Needleman-Wunsch provant els 12 transports.
"""

import json
import re
import sys

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BEMOLLS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}
# Perfils de Krumhansl-Kessler
MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MENOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def majmin(acord: str) -> tuple[int, str] | None:
    """'F#m7' o 'A:min7' → (arrel, 'maj'|'min'). None si no és un acord."""
    m = re.match(r"([A-G][#b]?)(.*)", acord.replace(":", ""))
    if not m:
        return None
    arrel = BEMOLLS.get(m.group(1), m.group(1))
    resta = m.group(2).split("/")[0]
    menor = resta.startswith("min") or (resta.startswith("m") and not resta.startswith("maj"))
    return NOTES.index(arrel), "min" if menor else "maj"


def col_lapsa(seq):
    return [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]


def nw(ref, pred):
    """Nombre d'encerts de l'alineament òptim (encert +1, error -1, forat -1)."""
    n, m = len(ref), len(pred)
    puntuacio = [[0] * (m + 1) for _ in range(n + 1)]
    encerts = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        puntuacio[i][0] = -i
    for j in range(1, m + 1):
        puntuacio[0][j] = -j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            igual = ref[i - 1] == pred[j - 1]
            opcions = [
                (puntuacio[i - 1][j - 1] + (1 if igual else -1), encerts[i - 1][j - 1] + igual),
                (puntuacio[i - 1][j] - 1, encerts[i - 1][j]),
                (puntuacio[i][j - 1] - 1, encerts[i][j - 1]),
            ]
            puntuacio[i][j], encerts[i][j] = max(opcions)
    return encerts[n][m]


def tonalitat(segments):
    """To per histograma de notes dels acords ponderat per durada + Krumhansl."""
    hist = [0.0] * 12
    for (arrel, tipus), durada in segments:
        for interval in (0, 3 if tipus == "min" else 4, 7):
            hist[(arrel + interval) % 12] += durada
    millor = None
    for t in range(12):
        for perfil, mode in ((MAJOR, ""), (MENOR, "m")):
            rot = [perfil[(i - t) % 12] for i in range(12)]
            mh, mr = sum(hist) / 12, sum(rot) / 12
            num = sum((h - mh) * (r - mr) for h, r in zip(hist, rot))
            den = (sum((h - mh) ** 2 for h in hist) * sum((r - mr) ** 2 for r in rot)) ** 0.5
            corr = num / den if den else 0
            if millor is None or corr > millor[0]:
                millor = (corr, NOTES[t] + mode)
    return millor[1], round(millor[0], 2)


ref_json = json.load(open(sys.argv[1], encoding="utf-8"))
min_durada = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
ref = col_lapsa([majmin(a) for a in re.findall(r"<ch>([^<]+)</ch>", ref_json["content"])])

segments = []
for l in open(sys.argv[2], encoding="utf-8"):
    inici, fi, etiqueta = l.split()[:3]
    durada = float(fi) - float(inici)
    if etiqueta not in ("N", "X") and durada >= min_durada:
        segments.append((majmin(etiqueta), durada))
pred = col_lapsa([a for a, _ in segments])

resultats = []
for despl in range(12):
    ref_t = [((r + despl) % 12, t) for r, t in ref]
    resultats.append((nw(ref_t, pred), despl))
encerts, despl = max(resultats)
to_pred, corr = tonalitat(segments)
print(json.dumps({
    "n_ref": len(ref), "n_pred": len(pred), "encerts": encerts,
    "precisio_ref": round(encerts / len(ref), 3),       # quanta referència es recupera
    "precisio_pred": round(encerts / max(len(pred), 1), 3),  # quant de la predicció és correcte
    "transport_semitons": despl, "to_bd": ref_json["key"], "capo_bd": ref_json["capo"],
    "to_estimat": to_pred, "corr_to": corr,
}, ensure_ascii=False))
