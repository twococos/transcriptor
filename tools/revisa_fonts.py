"""Mesura de les fonts d'acords externes (tabs) sobre el banc de proves, sense tocar cap resultat.

Per a cada cançó del banc (work/bench/dataset.jsonl) busca les tabs (es desen a work/fonts/<id>.json
i no es tornen a baixar) i compara, a nivell majmin i provant els 12 transports (bench.metrics.acords):
- tab ↔ BD (el content de la BD, que fa de referència del banc),
- tab ↔ anàlisi (el content d'un resultat del banc, per defecte v0113b),
- anàlisi ↔ BD (el punt de partida),
- tab ↔ tab (per detectar còpies).

Ús: uv run --no-sync python tools/revisa_fonts.py --banc [N] [--resultat v0113b] [--refes]
    uv run --no-sync python tools/revisa_fonts.py <id del banc>   (detall d'una cançó)
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from pathlib import Path

from transcriptor.bench.metrics import acords as metrica_acords
from transcriptor.cache import Cache
from transcriptor.stages.fetch import id_canco
from transcriptor.fonts import normalitza
from transcriptor.fonts.model import TabCrua
from transcriptor.stages import chords_source

BANC = Path("work/bench")
DESTI = Path("work/fonts")


def _dataset() -> list[dict]:
    return [json.loads(l) for l in (BANC / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def tabs_de(canco: dict, refes: bool = False) -> list[TabCrua]:
    """Les de la cache del banc (les desa `tx bench`), les d'aquesta eina, o es busquen."""
    audio = next((BANC / "audio").glob(f"{canco['id']}.*"), None)
    del_banc = Cache(id_canco(str(audio))).cami("chords_source.json") if audio else None
    if del_banc and del_banc.exists() and not refes:
        return [TabCrua.de_dict(d) for d in json.loads(del_banc.read_text(encoding="utf-8"))]
    f = DESTI / f"{canco['id']}.json"
    if f.exists() and not refes:
        return [TabCrua.de_dict(d) for d in json.loads(f.read_text(encoding="utf-8"))]
    tabs = chords_source.obte(canco["title"], canco["artist"], canco.get("language"))
    DESTI.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([t.a_dict() for t in tabs], ensure_ascii=False, indent=1), encoding="utf-8")
    return tabs


def _r(m: dict) -> tuple[float, float]:
    return m["acords_recall"], m["acords_precisio"]


def avalua(canco: dict, resultat: str, refes: bool) -> dict:
    tabs = tabs_de(canco, refes)
    pred_f = BANC / "resultats" / resultat / str(canco["id"]) / "content.txt"
    pred = pred_f.read_text(encoding="utf-8") if pred_f.exists() else None
    ref = canco["content"]
    fila = {"id": canco["id"], "titol": f"{canco['title']} — {canco['artist']}", "tabs": []}
    if pred:
        fila["pred_bd"] = _r(metrica_acords(ref, pred))
    continguts = []
    for t in tabs:
        c = normalitza.a_content(normalitza.tab(t))
        continguts.append(c)
        fila["tabs"].append({"lloc": t.lloc, "url": t.url, "vots": t.vots, "capo": t.capo,
                             "n": c.count("<ch>"), "bd": _r(metrica_acords(ref, c)),
                             "pred": _r(metrica_acords(c, pred)) if pred else None})
    fila["parells"] = [(i, j, _r(metrica_acords(continguts[i], continguts[j])))
                      for i in range(len(continguts)) for j in range(i + 1, len(continguts))]
    return fila


def _mitjana(xs) -> str:
    xs = list(xs)
    return f"{statistics.mean(xs) * 100:.1f} %" if xs else "—"


def resum(files: list[dict]) -> None:
    n = len(files)
    amb = [f for f in files if f["tabs"]]
    per_lloc: dict[str, list] = {}
    for f in files:
        for t in f["tabs"]:
            per_lloc.setdefault(t["lloc"], []).append(t)
    print(f"\nCançons: {n} · amb ≥1 tab: {len(amb)} ({len(amb) / max(n, 1):.0%}) · "
          f"amb ≥2 llocs: {sum(len({t['lloc'] for t in f['tabs']}) >= 2 for f in files)}")
    print(f"Anàlisi ↔ BD (recall/precisió): {_mitjana(f['pred_bd'][0] for f in files if 'pred_bd' in f)} / "
          f"{_mitjana(f['pred_bd'][1] for f in files if 'pred_bd' in f)}")
    print("\n| Lloc | cançons | tabs | tab↔BD recall | tab↔BD precisió | tab↔anàlisi recall | tab↔anàlisi precisió |")
    print("|---|---|---|---|---|---|---|")
    for lloc, ts in sorted(per_lloc.items()):
        cancons = sum(any(t["lloc"] == lloc for t in f["tabs"]) for f in files)
        ps = [t for t in ts if t["pred"]]
        print(f"| {lloc} | {cancons} | {len(ts)} | {_mitjana(t['bd'][0] for t in ts)} | {_mitjana(t['bd'][1] for t in ts)} "
              f"| {_mitjana(t['pred'][0] for t in ps)} | {_mitjana(t['pred'][1] for t in ps)} |")
    # La millor tab de cada cançó (cota superior d'una tria perfecta) i la primera (la més votada)
    millors = [max(t["bd"][0] for t in f["tabs"]) for f in amb]
    primeres = [f["tabs"][0]["bd"][0] for f in amb]
    pred_amb = [f["pred_bd"][0] for f in amb if "pred_bd" in f]
    print(f"\nCançons amb tabs: anàlisi↔BD recall {_mitjana(pred_amb)} · primera tab↔BD {_mitjana(primeres)} · "
          f"millor tab↔BD {_mitjana(millors)}")
    copies = [p for f in files for p in f["parells"] if p[2][0] >= 0.95 and p[2][1] >= 0.95]
    print(f"Parells de tabs gairebé idèntics (≥95 %): {len(copies)} de {sum(len(f['parells']) for f in files)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("id", nargs="?", type=int)
    ap.add_argument("--banc", nargs="?", const=0, type=int)
    ap.add_argument("--resultat", default="v0113b")
    ap.add_argument("--refes", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    dataset = _dataset()
    if args.id is not None:
        canco = next(c for c in dataset if c["id"] == args.id)
        fila = avalua(canco, args.resultat, args.refes)
        print(fila["titol"], "· anàlisi↔BD", fila.get("pred_bd"))
        for k, t in enumerate(fila["tabs"]):
            print(f"  [{k}] {t['lloc']:16} vots={t['vots']} capo={t['capo']} n={t['n']} bd={t['bd']} anàlisi={t['pred']}")
            print(f"      {t['url']}")
        for i, j, r in fila["parells"]:
            print(f"  [{i}]↔[{j}] {r}")
        return 0
    files = []
    for canco in dataset[: args.banc or None]:
        fila = avalua(canco, args.resultat, args.refes)
        files.append(fila)
        print(f"{fila['id']:4} {fila['titol'][:45]:45} tabs={len(fila['tabs'])} "
              + " ".join(f"{t['lloc'][:4]}:{t['bd'][0]:.2f}" for t in fila["tabs"]), flush=True)
    (DESTI / "resum.json").write_text(json.dumps(files, ensure_ascii=False, indent=1), encoding="utf-8")
    resum(files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
