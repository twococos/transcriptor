"""Revisa la correcció dels temps de Whisper (postprocess/temps_asr.py) sobre cançons ja transcrites per l'app.

Refà el postprocés amb les dades crues de la cache, amb i sense la correcció, i imprimeix:
- cada paraula de Whisper moguda (temps abans → després, amb les paraules del voltant);
- les línies de la lletra que han canviat d'inici o de final (més de 0.3 s).
Amb una cançó feta escriu work/revisio/lletra-<n>/analysis.json (amb la correcció) i l'àudio, per obrir-ho
amb `tx visor work/revisio/lletra-<n>`.

Ús: uv run --no-sync python tools/revisa_lletra.py [--sense-lletra] <n de fetes | yt-<id>> [...]
    --sense-lletra: lletra de Whisper encara que la cache en tingui una altra (com a les cançons que no
    eren a lrclib ni a la BD quan es van transcriure)
    (dades de l'app: %LOCALAPPDATA%/Transcriptor/dades; un altre directori amb TX_HOME)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from unittest import mock

import numpy as np

from transcriptor import __version__
from transcriptor.cache import Cache
from transcriptor.config import Config
from transcriptor.paquet import Crues
from transcriptor.pipeline import Entrada, executa
from transcriptor.postprocess import temps_asr

DADES = Path(os.environ.get("TX_HOME") or Path(os.environ.get("LOCALAPPDATA", "")) / "Transcriptor" / "dades")
SORTIDA = Path("work/revisio")
MIN_CANVI_LINIA_S = 0.3


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _llegeix(cache: Path, nom: str) -> dict:
    return json.loads((cache / nom).read_text(encoding="utf-8"))


def _crues(cache: Path, durada: float | None, sense_lletra: bool) -> Crues:
    """Les dades crues tal com són a la cache (sense comprovar-ne els paràmetres)."""
    ritme = _llegeix(cache, "rhythm.json")
    asr = _llegeix(cache, "lyrics_asr.json")
    params_asr = _llegeix(cache, "lyrics_asr.params.json")
    acords = np.load(cache / "chords.npz")
    groove = None
    if (cache / "groove_env.npz").exists():
        g = np.load(cache / "groove_env.npz")
        groove = {"env": g["env"], "planor": float(g["planor"])}
    lletra = {"text": None, "font": "whisper"} if sense_lletra or not (cache / "lyrics_source.json").exists() \
        else _llegeix(cache, "lyrics_source.json")
    if durada is None:
        durada = max([ritme["pulsacions"][-1]] + [p["end"] for p in asr["paraules"]]) + 1.0
    return Crues(meta=_llegeix(cache, "fetch.json"), durada=durada, ritme=ritme, probs=acords["probs"],
                 per_trama=float(acords["per_trama"]), asr=asr, idioma_asr=params_asr.get("idioma"),
                 lletra=lletra, groove=groove, separador=params_asr.get("veu", "htdemucs"),
                 compute_type=params_asr.get("compute_type", "int8"), versio=__version__)


def _linies(res) -> list[tuple[str, float, float]]:
    w = res.analisi.words
    return [(" ".join(p.text for p in w[l.word_range[0]:l.word_range[1]]), l.start, l.end) for l in res.analisi.lines]


def revisa(arg: str, sense_lletra: bool) -> None:
    feta = DADES / "fetes" / arg if not arg.startswith("yt-") else None
    analisi = json.loads((feta / "analysis.json").read_text(encoding="utf-8")) if feta else None
    id_canco = arg if not feta else f"yt-{analisi['source']['youtube_id']}"
    dir_cache = DADES / "cache" / id_canco
    crues = _crues(dir_cache, analisi["source"]["duration_s"] if analisi else None, sense_lletra)
    entrada = Entrada(font=crues.meta.get("url") or arg)

    def _executa():
        return executa(entrada, Config(), cache=Cache(id_canco, base=DADES / "cache"), dades=crues)

    with mock.patch.object(temps_asr, "corregeix",
                           lambda p, s: {"paraules": p, "segments": s, "correccions": []}):
        abans = _executa()
    despres = _executa()

    paraules = crues.asr["paraules"]
    correccions = temps_asr.corregeix(paraules, crues.asr["segments"])["correccions"]
    print(f"== {despres.analisi.meta.title} (lletra: {despres.analisi.lyrics_source}): "
          f"{len(correccions)} paraules de Whisper mogudes")
    k = 0
    for c in correccions:
        while not (paraules[k]["text"] == c["text"] and paraules[k]["start"] == c["abans"][0]):
            k += 1
        ant = paraules[k - 1]["text"] if k else ""
        seg = paraules[k + 1]["text"]
        print(f"   {_mmss(c['abans'][0])} → {_mmss(c['despres'][0])}  {ant} [{c['text']}] {seg}"
              f"   ({c['abans'][0]:.2f}-{c['abans'][1]:.2f} → {c['despres'][0]:.2f}-{c['despres'][1]:.2f})")

    la, ld = _linies(abans), _linies(despres)
    if [t for t, _, _ in la] != [t for t, _, _ in ld]:
        print("   Les línies han canviat:")
        for t, s, e in la:
            print(f"     abans   {_mmss(s)}–{_mmss(e)}  {t}")
        for t, s, e in ld:
            print(f"     després {_mmss(s)}–{_mmss(e)}  {t}")
    else:
        canvis = [(t, a, d) for (t, *a), (_, *d) in zip(la, ld)
                  if max(abs(a[0] - d[0]), abs(a[1] - d[1])) > MIN_CANVI_LINIA_S]
        print(f"   {len(canvis)} de {len(ld)} línies canvien d'inici o de final:")
        for t, a, d in canvis:
            print(f"     {_mmss(a[0])}–{_mmss(a[1])} → {_mmss(d[0])}–{_mmss(d[1])}  {t}")

    if not feta:
        return
    desti = SORTIDA / f"lletra-{arg}"
    desti.mkdir(parents=True, exist_ok=True)
    (desti / "analysis.json").write_text(despres.analisi.model_dump_json(indent=1), encoding="utf-8")
    for f in feta.glob("audio.*"):
        shutil.copy2(f, desti / f.name)
    print(f"   → tx visor {desti}")


def main() -> int:
    args = sys.argv[1:]
    sense_lletra = "--sense-lletra" in args
    args = [a for a in args if a != "--sense-lletra"]
    if not args:
        print(__doc__)
        return 1
    for arg in args:
        revisa(arg, sense_lletra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
