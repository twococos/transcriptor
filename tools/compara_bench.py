"""Compara dues execucions del banc (work/bench/resultats/<nom>/resultats.csv) cançó a cançó.

Ús: uv run --no-sync python tools/compara_bench.py <abans> <després> [--camps acords_recall,acords_precisio,...]
Només compara les cançons que són a totes dues. Imprimeix les mitjanes i les cançons que canvien més.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

RESULTATS = Path("work/bench/resultats")
CAMPS = ["acords_recall", "acords_precisio", "septimes_recall", "septimes_precisio", "collocacio", "estructura"]


def _llegeix(nom: str) -> dict[str, dict]:
    with open(RESULTATS / nom / "resultats.csv", encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f) if not r.get("error")}


def _num(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("abans")
    ap.add_argument("despres")
    ap.add_argument("--camps", default=",".join(CAMPS))
    ap.add_argument("--n", type=int, default=12, help="cançons que es mostren")
    args = ap.parse_args()
    a, d = _llegeix(args.abans), _llegeix(args.despres)
    ids = sorted(set(a) & set(d), key=int)
    camps = args.camps.split(",")
    print(f"{len(ids)} cançons en comú\n")
    print(f"| camp | {args.abans} | {args.despres} | diferència | millors | pitjors |")
    print("|---|---|---|---|---|---|")
    for c in camps:
        parells = [(x, y) for i in ids if (x := _num(a[i].get(c))) is not None and (y := _num(d[i].get(c))) is not None]
        if not parells:
            continue
        ma, md = statistics.mean(p[0] for p in parells), statistics.mean(p[1] for p in parells)
        print(f"| {c} | {ma:.1%} | {md:.1%} | {md - ma:+.1%} | {sum(y > x + 0.01 for x, y in parells)} "
              f"| {sum(y < x - 0.01 for x, y in parells)} |")
    c = camps[0]
    canvis = sorted(((_num(d[i][c]) or 0) - (_num(a[i][c]) or 0), i) for i in ids)
    print(f"\nCançons que canvien més ({c}):")
    for delta, i in canvis[: args.n // 2] + canvis[-(args.n // 2):]:
        if abs(delta) > 0.01:
            print(f"  {i:>4} {a[i]['titol'][:40]:40} {float(a[i][c]):.0%} → {float(d[i][c]):.0%} ({delta:+.0%})")


if __name__ == "__main__":
    main()
