"""`tx bench`: executa el pipeline sobre les cançons de la BD i en mesura la concordança.

Entrada: work/bench/dataset.jsonl (exportat en mode només lectura d'una còpia de canconer.db) i
l'àudio a work/bench/audio/<id>.*. La lletra es pren de la BD (mode "db"), com passarà quan es
reprocessi una cançó existent; el WER es calcula a part sobre la sortida de l'ASR.

Sortida a <out>/<nom>/: un directori per cançó (content.txt, analysis.json) + resultats.csv + resum.md.
"""

from __future__ import annotations

import csv
import json
import logging
import time
import traceback
from pathlib import Path

import numpy as np

from ..cache import Cache
from ..config import Config
from ..device import detecta
from ..notation import transposa
from ..pipeline import Entrada, executa
from ..stages.fetch import id_canco
from . import metrics

log = logging.getLogger(__name__)

ETAPES_CARES = ("audio.wav", "vocals.wav", "rhythm.json", "chords.npz", "lyrics_asr.json")


def _dataset(fitxer: Path, ids: set[int] | None, n: int) -> list[dict]:
    cancons = [json.loads(l) for l in fitxer.read_text(encoding="utf-8").splitlines() if l.strip()]
    if ids:
        cancons = [c for c in cancons if c["id"] in ids]
    # Publicades primer (referències revisades), després els esborranys
    cancons.sort(key=lambda c: (c["state"] != 0, c["id"]))
    return cancons[:n] if n else cancons


def avalua(canco: dict, content: str, analisi) -> dict:
    ref = canco["content"]
    fila = {"id": canco["id"], "titol": canco["title"], "artista": canco["artist"], "estat": canco["state"]}
    fila.update(metrics.qualitat_referencia(ref))
    ac = metrics.acords(ref, content)
    fila.update(ac)
    fila["to_ref"] = f"{canco['key']}+{canco['capo'] or 0}"
    fila["to_pred"] = analisi.key.clau if analisi.key else ""
    tonic_formes = transposa(analisi.key.tonic, -analisi.capo_suggerit) if analisi.key else None
    fila["to"] = metrics.tonalitat(canco["key"], ac["transport"], tonic_formes,
                                   analisi.key.mode if analisi.key else None)
    # El `key` de la BD sovint és l'arrel del primer acord (importadors): comparem també amb el to
    # estimat a partir dels acords escrits a la BD
    fila["to_acords_bd"] = metrics.tonalitat_acords_bd(ref, ac["transport"], tonic_formes,
                                                       analisi.key.mode if analisi.key else None)
    fila.update(metrics.collocacio(ref, content, ac["transport"]))
    fila.update(metrics.estructura(ref, content))
    fila["compas"] = f"{analisi.tempo.time_signature[0]}/{analisi.tempo.time_signature[1]}"
    fila["bpm"] = analisi.tempo.bpm
    fila["idioma"] = analisi.meta.language
    fila["aparellades"] = analisi.models.get("lyrics_aparellades", "")
    fila["temps_s"] = analisi.temps_etapes_s.get("total")
    return fila


def executa_bench(args) -> int:
    cfg = Config.carrega(args.config, lrclib=False)
    perfil = detecta(args.device)
    ids = {int(x) for x in args.ids.split(",")} if args.ids else None
    cancons = _dataset(Path(args.dataset), ids, args.n)
    desti = Path(args.out) / args.nom
    desti.mkdir(parents=True, exist_ok=True)
    (desti / "config.json").write_text(cfg.model_dump_json(indent=1), encoding="utf-8")

    files = []
    for k, canco in enumerate(cancons, 1):
        audio = next(Path(args.audio).glob(f"{canco['id']}.*"), None)
        if audio is None:
            log.warning("[%d/%d] %s: sense àudio", k, len(cancons), canco["title"])
            continue
        id_c = id_canco(str(audio))
        cache = Cache(id_c)
        if args.nomes_postproces and not all(cache.cami(f).exists() for f in ETAPES_CARES):
            log.info("[%d/%d] %s: no és a la cache, se salta", k, len(cancons), canco["title"])
            continue
        log.info("[%d/%d] %s — %s", k, len(cancons), canco["title"], canco["artist"])
        inici = time.perf_counter()
        try:
            res = executa(Entrada(font=str(audio), titol=canco["title"], artista=canco["artist"],
                                  content_bd=canco["content"]), cfg, perfil, cache)
        except Exception as e:  # noqa: BLE001 — una cançó que falla no atura el lot
            log.error("%s: %s", canco["title"], e)
            (desti / f"{canco['id']}.error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            files.append({"id": canco["id"], "titol": canco["title"], "error": str(e)[:200]})
            continue
        dir_c = desti / str(canco["id"])
        dir_c.mkdir(exist_ok=True)
        (dir_c / "content.txt").write_text(res.content, encoding="utf-8", newline="\n")
        (dir_c / "referencia.txt").write_text(canco["content"], encoding="utf-8", newline="\n")
        (dir_c / "analysis.json").write_text(res.analisi.model_dump_json(indent=1), encoding="utf-8")
        fila = avalua(canco, res.content, res.analisi)
        asr = json.loads(cache.cami("lyrics_asr.json").read_text(encoding="utf-8"))
        fila["wer"] = metrics.wer_lletra(canco["content"], " ".join(s["text"] for s in asr["segments"]))
        fila["temps_s"] = round(time.perf_counter() - inici, 1)
        files.append(fila)
        log.info("   acords %.0f%% · to %s · col·locació %.0f%% · estructura %.0f%% · WER %.2f · %.0f s",
                 100 * fila["acords_recall"], fila["to"], 100 * fila["collocacio"],
                 100 * fila["estructura"], fila["wer"], fila["temps_s"])
        _desa(files, desti)
    _desa(files, desti)
    print((desti / "resum.md").read_text(encoding="utf-8"))
    return 0


def _desa(files: list[dict], desti: Path) -> None:
    camps = list(dict.fromkeys(k for f in files for k in f))
    with open(desti / "resultats.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=camps)
        w.writeheader()
        w.writerows(files)
    (desti / "resum.md").write_text(resum(files), encoding="utf-8")


def _mitjana(files: list[dict], camp: str) -> str:
    v = [f[camp] for f in files if isinstance(f.get(camp), (int, float))]
    return f"{100 * np.mean(v):.1f} %" if v else "—"


def resum(files: list[dict]) -> str:
    ok = [f for f in files if "error" not in f]
    netes = [f for f in ok if not f.get("ref_problemes")]
    linies = [f"# Benchmark ({len(ok)} cançons, {len(files) - len(ok)} errors)", ""]
    for nom, grup in (("Totes", ok), ("Referències sense problemes", netes),
                      ("Publicades", [f for f in ok if f.get("estat") == 0])):
        if not grup:
            continue
        tons = {}
        for f in grup:
            tons[f["to"]] = tons.get(f["to"], 0) + 1
        linies += [
            f"## {nom} ({len(grup)})", "",
            "| Mètrica | Valor |", "|---|---|",
            f"| Acords majmin: recuperat de la BD | {_mitjana(grup, 'acords_recall')} |",
            f"| Acords majmin: correcte del predit | {_mitjana(grup, 'acords_precisio')} |",
            f"| Acords sevenths: recuperat / correcte | {_mitjana(grup, 'septimes_recall')} / {_mitjana(grup, 'septimes_precisio')} |",
            f"| Col·locació (mateixa paraula) | {_mitjana(grup, 'collocacio')} |",
            f"| Estructura (tipus de secció per línia) | {_mitjana(grup, 'estructura')} |",
            f"| WER de l'ASR (orientatiu) | {np.mean([f['wer'] for f in grup if 'wer' in f]):.3f} |",
            f"| To (vs `key` de la BD) | {', '.join(f'{k}: {v}' for k, v in sorted(tons.items(), key=lambda x: -x[1]))} |",
            f"| To (vs to dels acords de la BD) | {sum(f.get('to_acords_bd') == 'exacte' for f in grup)}/{len(grup)} exacte |",
            f"| Temps mitjà per cançó | {np.mean([f['temps_s'] for f in grup]):.0f} s |",
            "",
        ]
    linies += ["## Per cançó", "",
               "| id | Cançó | Acords | Precisió | Col·loc. | Estruct. | To (ref → pred) | Compàs | WER | Ref. |",
               "|---|---|---|---|---|---|---|---|---|---|"]
    for f in ok:
        linies.append(
            f"| {f['id']} | {f['titol']} — {f['artista']} | {100 * f['acords_recall']:.0f} % | "
            f"{100 * f['acords_precisio']:.0f} % | {100 * f['collocacio']:.0f} % | {100 * f['estructura']:.0f} % | "
            f"{f['to_ref']} → {f['to_pred']} ({f['to']}) | {f['compas']} | {f.get('wer', '')} | "
            f"{f.get('ref_problemes') or 'ok'} |")
    for f in files:
        if "error" in f:
            linies.append(f"| {f['id']} | {f['titol']} | ERROR: {f['error']} |||||||| ")
    return "\n".join(linies) + "\n"
