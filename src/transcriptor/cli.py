"""CLI `tx`.

    tx run <url|fitxer> [--lyrics fitxer.txt] [--title T] [--artist A] [--lang ca] [--device auto]
    tx bench [--n 20] [--ids 110,111] [--config configs/x.yaml]
    tx worker --api https://guitarreo.cat --token ... [--device auto]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__


def _configura_logs(verbos: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbos else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for soroll in ("httpx", "httpx2", "huggingface_hub", "urllib3", "faster_whisper", "numba", "matplotlib"):
        logging.getLogger(soroll).setLevel(logging.WARNING)


def _run(args) -> int:
    from .config import Config
    from .device import detecta
    from .pipeline import Entrada, executa

    cfg = Config.carrega(args.config)
    perfil = detecta(args.device)
    text = Path(args.lyrics).read_text(encoding="utf-8") if args.lyrics else None
    res = executa(Entrada(font=args.font, titol=args.title, artista=args.artist, idioma=args.lang,
                          text_usuari=text), cfg, perfil)
    desti = Path(args.out) / (res.analisi.source.youtube_id or Path(args.font).stem)
    desti.mkdir(parents=True, exist_ok=True)
    # newline="\n": a Windows, write_text convertiria els salts a \r\n i trencaria el format de la BD
    (desti / "analysis.json").write_text(res.analisi.model_dump_json(indent=1), encoding="utf-8", newline="\n")
    (desti / "content.txt").write_text(res.content, encoding="utf-8", newline="\n")
    (desti / "proposta.json").write_text(res.proposta.model_dump_json(indent=1), encoding="utf-8", newline="\n")
    print(res.content)
    print(f"\n→ {desti}  (to {res.proposta.key}, capo {res.proposta.capo}, "
          f"{res.analisi.tempo.bpm} BPM {res.analisi.tempo.time_signature[0]}/{res.analisi.tempo.time_signature[1]}, "
          f"lletra: {res.analisi.lyrics_source}, {res.analisi.temps_etapes_s.get('total')} s)", file=sys.stderr)
    return 0


def _bench(args) -> int:
    from .bench.runner import executa_bench

    return executa_bench(args)


def _worker(args) -> int:
    from .worker import executa_worker

    return executa_worker(args)


def main(argv: list[str] | None = None) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="tx", description="Transcriptor de cançons per a El Cançoner")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-v", "--verbos", action="store_true")
    sub = p.add_subparsers(dest="ordre", required=True)

    r = sub.add_parser("run", help="Analitza una cançó (URL de YouTube o fitxer d'àudio)")
    r.add_argument("font")
    r.add_argument("--lyrics", help="Fitxer de text amb la lletra (una línia per vers)")
    r.add_argument("--title")
    r.add_argument("--artist")
    r.add_argument("--lang", default=None, help="Idioma (ca, es...). Per defecte el detecta Whisper")
    r.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    r.add_argument("--config")
    r.add_argument("--out", default="out")
    r.set_defaults(func=_run)

    b = sub.add_parser("bench", help="Benchmark contra les cançons de la BD")
    b.add_argument("--dataset", default="work/bench/dataset.jsonl")
    b.add_argument("--audio", default="work/bench/audio")
    b.add_argument("--n", type=int, default=0, help="Màxim de cançons (0 = totes)")
    b.add_argument("--ids", help="Ids separats per comes")
    b.add_argument("--config")
    b.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    b.add_argument("--out", default="work/bench/resultats")
    b.add_argument("--nom", default="base", help="Nom de l'execució (per comparar configuracions)")
    b.add_argument("--nomes-postproces", action="store_true",
                   help="No calcula res de nou: només repeteix el postprocés sobre la cache")
    b.set_defaults(func=_bench)

    w = sub.add_parser("worker", help="Demana feines a l'API del canconer i les processa")
    w.add_argument("--api", required=True)
    w.add_argument("--token", required=True)
    w.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    w.add_argument("--config")
    w.add_argument("--nom", default=None, help="Nom del worker (per defecte, el de l'ordinador)")
    w.add_argument("--una", action="store_true", help="Processa una sola feina i surt")
    w.set_defaults(func=_worker)

    args = p.parse_args(argv)
    _configura_logs(args.verbos)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
