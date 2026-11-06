"""Revisa la correcció de pulsacions (postprocess/pulsacions.py) sobre cançons ja transcrites per l'app.

Llegeix `rhythm.json` i `chords.npz` crus de la cache i, si n'hi ha, la cançó feta (`fetes/<n>`).
Imprimeix les correccions i el tempo per trams de 10 s abans i després. Amb una cançó feta escriu
work/revisio/<n>/analysis.json (pulsacions i acords refets; la resta igual) i l'àudio, per obrir-ho
amb `tx visor work/revisio/<n>`.

Ús: uv run --no-sync python tools/revisa_ritme.py <n de fetes | yt-<id>> [...]
    (dades de l'app: %LOCALAPPDATA%/Transcriptor/dades; un altre directori amb TX_HOME)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

from transcriptor.config import Config
from transcriptor.pipeline import ritme_i_acords

DADES = Path(os.environ.get("TX_HOME") or Path(os.environ.get("LOCALAPPDATA", "")) / "Transcriptor" / "dades")
SORTIDA = Path("work/revisio")


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _tempos(pulsacions: list[float]) -> str:
    p = np.asarray(pulsacions)
    ibi = np.diff(p)
    trams = []
    for t0 in range(0, int(p[-1]), 10):
        dins = (p[:-1] >= t0) & (p[:-1] < t0 + 10)
        trams.append(f"{60 / np.median(ibi[dins]):.0f}" if dins.sum() > 2 else "-")
    return " ".join(trams)


def revisa(arg: str) -> None:
    feta = DADES / "fetes" / arg if not arg.startswith("yt-") else None
    analisi = json.loads((feta / "analysis.json").read_text(encoding="utf-8")) if feta else None
    cache = DADES / "cache" / (arg if not feta else f"yt-{analisi['source']['youtube_id']}")
    ritme = json.loads((cache / "rhythm.json").read_text(encoding="utf-8"))
    dades = np.load(cache / "chords.npz")
    durada = analisi["source"]["duration_s"] if analisi else ritme["pulsacions"][-1] + 1.0

    correccions, compas, segs, _ = ritme_i_acords(ritme, dades["probs"], float(dades["per_trama"]), durada,
                                                  Config())
    titol = analisi["meta"]["title"] if analisi else arg
    print(f"== {titol}: {compas['bpm']} BPM {compas['time_signature'][0]}/{compas['time_signature'][1]}, "
          f"{len(correccions)} correccions")
    for c in correccions:
        print(f"   {c['tipus']:7} {_mmss(c['inici'])}–{_mmss(c['fi'])}  {c['abans']} → {c['despres']} pulsacions")
    print("   abans:  ", _tempos(ritme["pulsacions"]))
    print("   després:", _tempos([b["t"] for b in compas["beats"]]))

    if not analisi:
        return
    pulsacio = {round(b["t"], 3): b for b in compas["beats"]}
    analisi["tempo"] = {"bpm": compas["bpm"], "time_signature": compas["time_signature"]}
    analisi["beats"] = compas["beats"]
    analisi["chords"] = []
    for s in segs:
        b = pulsacio.get(round(s["start"], 3))
        analisi["chords"].append({"start": s["start"], "end": s["end"], "label": s["label"], "raw": s["label"],
                                  "bar": b["bar"] if b else None, "beat": b["beat"] if b else None,
                                  "conf": s["conf"]})
    desti = SORTIDA / arg
    desti.mkdir(parents=True, exist_ok=True)
    (desti / "analysis.json").write_text(json.dumps(analisi, ensure_ascii=False), encoding="utf-8")
    for f in feta.glob("audio.*"):
        shutil.copy2(f, desti / f.name)
    print(f"   → tx visor {desti}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for arg in sys.argv[1:]:
        revisa(arg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
