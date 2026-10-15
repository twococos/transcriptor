"""Escombrat de paràmetres del postprocés sobre les cançons del benchmark que ja són a la cache.

Ús: python proves/escombrat.py <mòdul.CONSTANT> <valor1> <valor2> ... [--config fitxer.yaml]
Ex.: python proves/escombrat.py transcriptor.merge.PENALITZACIO_POSTERIOR 1 1.5 2 3

No recalcula res car: només el postprocés (acords per pulsació, compàs, fusió, estructura, render).
Imprimeix la mitjana de cada mètrica per valor.
"""

import importlib
import json
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from transcriptor.bench import metrics  # noqa: E402
from transcriptor.bench.runner import ETAPES_CARES, avalua  # noqa: E402
from transcriptor.cache import Cache  # noqa: E402
from transcriptor.config import Config  # noqa: E402
from transcriptor.device import detecta  # noqa: E402
from transcriptor.pipeline import Entrada, executa  # noqa: E402
from transcriptor.stages.fetch import id_canco  # noqa: E402

logging.basicConfig(level=logging.WARNING)
args = sys.argv[1:]
config = None
if "--config" in args:
    i = args.index("--config")
    config = args[i + 1]
    args = args[:i] + args[i + 2:]
nom_complet, valors = args[0], [float(v) if v.replace(".", "", 1).lstrip("-").isdigit() else v for v in args[1:]]
modul_nom, constant = nom_complet.rsplit(".", 1)
modul = importlib.import_module(modul_nom)

cancons = [json.loads(l) for l in Path("work/bench/dataset.jsonl").read_text(encoding="utf-8").splitlines() if l]
casos = []
for c in cancons:
    audio = next(Path("work/bench/audio").glob(f"{c['id']}.*"), None)
    if audio is None:
        continue
    cache = Cache(id_canco(str(audio)))
    if all(cache.cami(f).exists() for f in ETAPES_CARES):
        casos.append((c, audio, cache))
print(f"{len(casos)} cançons a la cache")

cfg = Config.carrega(config, lrclib=False)
perfil = detecta("cpu")
original = getattr(modul, constant)
for valor in valors:
    setattr(modul, constant, valor)
    files = []
    for c, audio, cache in casos:
        res = executa(Entrada(font=str(audio), titol=c["title"], artista=c["artist"], content_bd=c["content"]),
                      cfg, perfil, cache)
        files.append(avalua(c, res.content, res.analisi))
    m = {k: np.mean([f[k] for f in files]) for k in ("acords_recall", "acords_precisio", "collocacio", "estructura")}
    tons = sum(f["to"] == "exacte" for f in files)
    print(f"{constant}={valor}: acords {100 * m['acords_recall']:.1f} / {100 * m['acords_precisio']:.1f} · "
          f"col·locació {100 * m['collocacio']:.1f} · estructura {100 * m['estructura']:.1f} · "
          f"to exacte {tons}/{len(files)}")
setattr(modul, constant, original)
