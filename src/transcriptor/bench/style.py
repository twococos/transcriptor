"""`tx estils`: banc de l'estil rítmic (postprocess/style.py) contra etiquetes fetes a mà.

Entrada:
  - un CSV `id,titol,artista,estil[,detectat]` (`estil` = l'etiqueta bona, un dels STYLE_IDS; buit = no
    etiquetada). Amb `--plantilla` es genera a partir del dataset del banc, amb l'estil detectat ara
    com a pista, per omplir-lo.
  - les anàlisis d'una execució del banc (temps i compàs) i la cache de cada cançó (àudio i veu).

Sortida: encert al primer estil i entre els tres primers, matriu de confusió i un CSV per cançó.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from pathlib import Path

from ..cache import Cache
from ..postprocess import style
from ..stages import groove
from ..stages.fetch import id_canco

log = logging.getLogger(__name__)


def _empremta(sid: int, audio_dir: Path, resultats: Path) -> tuple[dict | None, float | None, list[int] | None]:
    f = resultats / str(sid) / "analysis.json"
    audio = next(audio_dir.glob(f"{sid}.*"), None)
    if not f.exists() or audio is None:
        return None, None, None
    a = json.loads(f.read_text(encoding="utf-8"))
    cache = Cache(id_canco(str(audio)))
    mescla, veu = cache.cami("audio.wav"), cache.cami("vocals.wav")
    if not (mescla.exists() and veu.exists()):
        return None, None, None
    ts = a["tempo"]["time_signature"]
    return groove.empremta(mescla, veu, a["beats"], ts), a["tempo"]["bpm"], ts


def plantilla(args) -> int:
    desti = Path(args.etiquetes)
    if desti.exists():
        log.error("%s ja existeix: no el sobreescric", desti)
        return 1
    cancons = [json.loads(l) for l in Path(args.dataset).read_text(encoding="utf-8").splitlines() if l.strip()]
    with open(desti, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "titol", "artista", "estil", "detectat"])
        for c in sorted(cancons, key=lambda c: c["id"]):
            emp, bpm, ts = _empremta(c["id"], Path(args.audio), Path(args.resultats))
            detectat = style.classifica(emp, bpm, ts)["style"] if emp else ""
            w.writerow([c["id"], c["title"], c["artist"], "", detectat])
    print(f"Plantilla a {desti}. Omple la columna `estil` amb un de: {', '.join(style.STYLE_IDS)}")
    return 0


def executa(args) -> int:
    if args.plantilla:
        return plantilla(args)
    files = list(csv.DictReader(open(args.etiquetes, encoding="utf-8")))
    etiquetades = [f for f in files if f.get("estil", "").strip()]
    desconegudes = sorted({f["estil"] for f in etiquetades} - set(style.STYLE_IDS))
    if desconegudes:
        log.error("Estils desconeguts a les etiquetes: %s", ", ".join(desconegudes))
        return 1
    resultats = []
    for f in etiquetades:
        sid = int(f["id"])
        emp, bpm, ts = _empremta(sid, Path(args.audio), Path(args.resultats))
        if emp is None:
            log.warning("%s: sense anàlisi o sense àudio a la cache, se salta", sid)
            continue
        r = style.classifica(emp, bpm, ts)
        top3 = [r["style"]] + [a[0] for a in r["alternatives"][:2]]
        resultats.append({"id": sid, "titol": f.get("titol", ""), "estil": f["estil"], "predit": r["style"],
                          "confianca": r["confidence"], "top3": f["estil"] in top3,
                          "alternatives": " ".join(f"{s}:{p}" for s, p in r["alternatives"])})
    if not resultats:
        print("Cap cançó etiquetada amb àudio a la cache.")
        return 1

    n = len(resultats)
    encert = sum(r["estil"] == r["predit"] for r in resultats) / n
    encert3 = sum(r["top3"] for r in resultats) / n
    linies = [f"# Estil rítmic ({n} cançons etiquetades)", "",
              f"- Encert (primer): {100 * encert:.1f} %", f"- Entre els tres primers: {100 * encert3:.1f} %", "",
              "## Confusions (etiqueta → predit)", ""]
    for (e, p), k in Counter((r["estil"], r["predit"]) for r in resultats if r["estil"] != r["predit"]).most_common():
        linies.append(f"- {e} → {p}: {k}")
    linies += ["", "## Per estil", "", "| estil | n | encert |", "|---|---|---|"]
    for e in style.STYLE_IDS:
        grup = [r for r in resultats if r["estil"] == e]
        if grup:
            ok = sum(r["predit"] == e for r in grup)
            linies.append(f"| {e} | {len(grup)} | {100 * ok / len(grup):.0f} % |")
    resum = "\n".join(linies)
    desti = Path(args.out)
    desti.mkdir(parents=True, exist_ok=True)
    with open(desti / "estils.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(resultats[0]))
        w.writeheader()
        w.writerows(resultats)
    (desti / "estils.md").write_text(resum, encoding="utf-8")
    print(resum)
    return 0
