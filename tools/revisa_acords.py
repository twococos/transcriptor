"""Revisa els acords per patrons de compàs i les seccions quadrades (0.1.13) sobre cançons ja transcrites.

Refà el postprocés amb les dades crues de la cache, abans (Viterbi per pulsació i seccions sense
quadrar) i després, i imprimeix les seccions (inici en compàs.temps i llargada en compassos) i el
content nou. Amb una cançó feta escriu work/revisio/acords-<n>/analysis.json i l'àudio, per obrir-ho
amb `tx visor work/revisio/acords-<n>`.

Amb --totes [N] no imprimeix cap cançó: fa l'estadística de les N fetes més recents (per defecte 60):
temps del compàs on comencen els acords, durades en temps, seccions a terra, forats/solapaments
entre seccions i llargades múltiples de 4.

Ús: uv run --no-sync python tools/revisa_acords.py <n de fetes | yt-<id>> [...]
    uv run --no-sync python tools/revisa_acords.py --totes [N]
    (dades de l'app: %LOCALAPPDATA%/Transcriptor/dades; un altre directori amb TX_HOME)
"""

from __future__ import annotations

import bisect
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from unittest import mock

import numpy as np

from transcriptor.cache import Cache
from transcriptor.config import Config
from transcriptor.pipeline import Entrada, executa
from transcriptor.postprocess import chords_clean, seccions

sys.path.insert(0, str(Path(__file__).parent))
from revisa_lletra import DADES, _crues  # noqa: E402

SORTIDA = Path("work/revisio")


def _viterbi_vell(p_unitat, beats, desfasament):
    inici = np.array([False] * desfasament + [b["beat"] == 1 for b in beats] + [False])
    return chords_clean.viterbi(p_unitat, inici[: len(p_unitat)])


def _executa(arg: str, analisi: dict | None, vell: bool):
    id_canco = arg if not analisi else f"yt-{analisi['source']['youtube_id']}"
    crues = _crues(DADES / "cache" / id_canco, analisi["source"]["duration_s"] if analisi else None, False)
    entrada = Entrada(font=crues.meta.get("url") or arg)
    if not vell:
        return executa(entrada, Config(), cache=Cache(id_canco, base=DADES / "cache"), dades=crues)
    with mock.patch.object(chords_clean, "viterbi_compas", _viterbi_vell), \
            mock.patch.object(seccions, "quadra", lambda e, s, *_: (e, s)):
        return executa(entrada, Config(), cache=Cache(id_canco, base=DADES / "cache"), dades=crues)


def _posicio(beats, t: float) -> tuple[int, int, float]:
    """(índex de pulsació, compàs, temps) de la pulsació més propera a t."""
    ts = [b.t for b in beats]
    k = bisect.bisect_left(ts, t)
    k = min((j for j in (k - 1, k) if 0 <= j < len(ts)), key=lambda j: abs(ts[j] - t))
    return k, beats[k].bar, beats[k].beat


def _seccions(res) -> list[tuple[str, str, float, float]]:
    """(nom, inici en compàs.temps, llargada en compassos, forat amb la següent en temps)."""
    a = res.analisi
    per_compas = a.tempo.time_signature[0]
    sortida = []
    for i, s in enumerate(a.sections):
        k, bar, beat = _posicio(a.beats, s.start)
        kf, _, _ = _posicio(a.beats, s.end)
        forat = None
        if i + 1 < len(a.sections):
            forat = _posicio(a.beats, a.sections[i + 1].start)[0] - kf
        sortida.append((s.name, f"{bar}.{beat}", (kf - k) / per_compas, forat))
    return sortida


def _estadistica(res, acum: dict) -> None:
    a = res.analisi
    ts = [b.t for b in a.beats]
    for c in a.chords:
        k, _, beat = _posicio(a.beats, c.start)
        acum["inici"][beat] += 1
        acum["durada"][min(bisect.bisect_left(ts, c.end - 1e-3) - k, 9)] += 1
    for _, pos, llarg, forat in _seccions(res):
        acum["sec_terra"][pos.endswith(".1")] += 1
        acum["sec_mult4"][abs(llarg - round(llarg)) < 1e-6 and round(llarg) % 4 == 0] += 1
        acum["llargada"][round(llarg * 4) / 4] += 1
        if forat is not None:
            acum["forat"][forat] += 1


def totes(n: int) -> None:
    fetes = sorted((p for p in (DADES / "fetes").iterdir() if (p / "analysis.json").exists()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    acum = {nom: {k: Counter() for k in ("inici", "durada", "sec_terra", "sec_mult4", "llargada", "forat")}
            for nom in ("abans", "després")}
    fetes_ok = 0
    for feta in fetes:
        if fetes_ok >= n:
            break
        analisi = json.loads((feta / "analysis.json").read_text(encoding="utf-8"))
        try:
            parells = [(nom, _executa(feta.name, analisi, nom == "abans")) for nom in ("abans", "després")]
        except Exception as e:  # noqa: BLE001 — cache incompleta: se salta
            print(f"   {feta.name}: {type(e).__name__} {e}"[:120])
            continue
        fetes_ok += 1
        for nom, res in parells:
            _estadistica(res, acum[nom])
    print(f"{fetes_ok} cançons")
    for nom, c in acum.items():
        total = sum(c["inici"].values())
        n_sec = sum(c["sec_terra"].values())
        print(f"== {nom}: {total} acords, {n_sec} seccions")
        print("   inici (temps del compàs):", {k: f"{v / total:.1%}" for k, v in sorted(c["inici"].items())})
        print("   durades (temps):", sorted(c["durada"].items()))
        print(f"   seccions a terra: {c['sec_terra'][True] / n_sec:.1%} · múltiples de 4: "
              f"{c['sec_mult4'][True] / n_sec:.1%}")
        print(f"   llargades (compassos): {sorted(c['llargada'].items())}")
        print(f"   forats entre seccions (temps): {sorted(c['forat'].items())}")


def revisa(arg: str) -> None:
    feta = DADES / "fetes" / arg if not arg.startswith("yt-") else None
    analisi = json.loads((feta / "analysis.json").read_text(encoding="utf-8")) if feta else None
    abans, despres = _executa(arg, analisi, True), _executa(arg, analisi, False)
    print(f"== {despres.analisi.meta.title}: {despres.analisi.tempo.bpm} BPM "
          f"{despres.analisi.tempo.time_signature[0]}/{despres.analisi.tempo.time_signature[1]}")
    for nom, res in (("abans", abans), ("després", despres)):
        print(f"   seccions {nom}:")
        for s, pos, llarg, forat in _seccions(res):
            print(f"     {pos:>7}  {llarg:5.2f} compassos  {s}" + (f"  (forat {forat} temps)" if forat else ""))
    print(despres.content)
    if not feta:
        return
    desti = SORTIDA / f"acords-{arg}"
    desti.mkdir(parents=True, exist_ok=True)
    (desti / "analysis.json").write_text(despres.analisi.model_dump_json(indent=1), encoding="utf-8")
    for f in feta.glob("audio.*"):
        shutil.copy2(f, desti / f.name)
    print(f"   → tx visor {desti}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--totes":
        totes(int(args[1]) if len(args) > 1 else 60)
        return 0
    for arg in args:
        revisa(arg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
