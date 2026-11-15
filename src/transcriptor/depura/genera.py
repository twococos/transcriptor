"""Traça d'una cançó per al depurador: el postprocés pas a pas, sense tabs i la referència.

    python -m transcriptor.depura.genera <clau> [--refes]

La clau diu d'on surt la cançó (vegeu origens.py):
- `banc-<id>`: una cançó del banc. Repeteix el postprocés com `tx bench` (mateixa configuració i
  cache), només amb el que ja és a la cache (`sense_audio`): si hi falta alguna etapa, falla.
- `web-<id>`: una cançó del canconer. Es baixen les dades que rebria un worker en una feina
  `update` (dades crues, content, fonts d'acords, anàlisi) i es refà el postprocés com ell.
- `local-<w|a>-<cache>`: una cache local (w: la de work/, de `tx run` o del banc; a: la de l'app).
- `fitxer-<hash>`: un analysis.json sense dades crues: només es mostra l'anàlisi.

Desa `work/depura/<clau>/traca-<codi>.json`, on `codi` és un hash del codi font: si el codi no ha
canviat, no es torna a calcular.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

from .. import __version__, render
from ..bench import metrics
from ..bench.runner import avalua
from ..config import Config
from ..device import detecta
from ..notation import transposa
from ..pipeline import executa
from ..postprocess import rodes
from ..schema import SongAnalysis
from ..text import normalitza
from ..traca import Traca, net
from . import origens
from .origens import DATASET, audio_de, dataset, dir_traces  # noqa: F401 — servidor.py les fa servir d'aquí

log = logging.getLogger(__name__)

SRC = Path(__file__).resolve().parents[1]


def codi() -> str:
    """Hash del codi del transcriptor: una traça feta amb un altre codi no serveix."""
    h = hashlib.sha1()
    for f in sorted(SRC.rglob("*.py")):
        h.update(f.relative_to(SRC).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def cami_traca(clau: str, hash_codi: str | None = None) -> Path:
    return dir_traces() / clau / f"traca-{hash_codi or codi()}.json"


def _referencia(ref: str | None, content: str, elements: list[dict], paraules: list, capo: int) -> dict:
    """Els acords de la referència al temps de l'anàlisi: cada línia de lletra s'aparella per text amb
    una línia de l'anàlisi (com metrics.collocacio) i cada acord va a la paraula on cau. Els de les
    línies sense lletra es reparteixen entre les línies aparellades del costat (`aprox`)."""
    if not ref:
        return {"content": "", "transport": 0, "capo": capo, "acords": [], "seccions": [], "sense_posicio": []}
    ref_d = metrics.desplega_repeticions(ref)
    transport = metrics.acords(ref_d, metrics.desplega_repeticions(content))["transport"] if content else 0
    linies = [e for e in elements if e["tipus"] == "linia"]
    claus = [" ".join(normalitza(e["text"])) for e in linies]
    sonant = transport + capo  # referència (formes) → so de l'anàlisi

    def acord(a: str, t: float, aprox: bool, li: int) -> dict:
        return {"t": t, "escrit": a, "label": transposa(a, sonant) if sonant else a, "aprox": aprox, "linia": li}

    acords, seccions, sense_posicio, pendents = [], [], [], []
    ultim_fi, j = 0.0, 0
    for li, l in enumerate(metrics.llegeix_content(ref_d)):
        if l["tipus"] == "sec":
            seccions.append({"name": l["text"], "start": None, "linia": li})
            continue
        if l["tipus"] == "acords":
            pendents.append((li, l))
            continue
        clau = " ".join(normalitza(l["text"]))
        try:
            k = claus.index(clau, j)
        except ValueError:
            sense_posicio.append(l["text"].strip())
            continue
        j = k + 1
        e = linies[k]
        a, b = e["word_range"]
        if pendents:  # línies d'acords entre la línia aparellada anterior i aquesta
            tots = [(lp, x) for lp, p in pendents for _, x in p["acords"]]
            pas = (e["start"] - ultim_fi) / max(len(tots), 1)
            acords += [acord(x, ultim_fi + q * pas, True, lp) for q, (lp, x) in enumerate(tots)]
            pendents = []
        for pos, x in l["acords"]:
            w = min(a + metrics._index_paraula(l["text"], pos), b - 1)
            acords.append(acord(x, paraules[w].start if b > a else e["start"], False, li))
        if seccions and seccions[-1]["start"] is None:
            seccions[-1]["start"] = e["start"]
        ultim_fi = e["end"]
    seccions = [s for s in seccions if s["start"] is not None]
    for s, seg in zip(seccions, seccions[1:] + [None]):
        s["end"] = seg["start"] if seg else None
    return {"content": ref, "transport": transport, "capo": capo, "acords": acords, "seccions": seccions,
            "sense_posicio": sense_posicio}


def _rodes(elements: list[dict], seccions: list[dict]) -> list[dict]:
    """Rodes de cada zona instrumental (tal com les dibuixa el render) i les quasi-rodes."""
    sortida = []
    for s in seccions:
        for e in render._zones(elements, s["elements"]):
            puls = e.get("pulsacions")
            if e["tipus"] != "instrumental" or not puls:
                continue
            trossos = [{"inici": t.originals[0][0][0], "vegades": t.vegades, "P": len(t.compassos)}
                       for t in rodes.trossos(puls) if t.vegades > 1]
            sortida.append({"seccio": s["name"], "start": e["start"], "end": e["end"],
                            "compassos": len(rodes.compassos(puls)), "rodes": trossos,
                            "quasi": rodes.quasi_rodes(puls)})
    return sortida


def _passos_de_analisi(a: SongAnalysis, content: str) -> dict:
    """Sense dades crues no es pot refer res: els passos es fan amb l'anàlisi final perquè la pàgina
    pugui mostrar-la igualment (acords, lletra i seccions)."""
    beats = [b.t for b in a.beats]
    paraules = [w.model_dump() for w in a.words]
    elements = [{"tipus": "linia", "start": l.start, "end": l.end, "word_range": list(l.word_range),
                 "text": " ".join(w.text for w in a.words[l.word_range[0]:l.word_range[1]]), "acords": []}
                for l in a.lines]
    seccions = [{"label": s.label.capitalize(), "name": s.name, "start": s.start, "end": s.end, "elements": []}
                for s in a.sections]
    segs = [{"start": c.start, "end": c.end, "label": c.label, "raw": c.raw, "conf": c.conf} for c in a.chords]
    return net({
        "ritme": {"pulsacions_crues": beats, "inicis_compas_crus": [b.t for b in a.beats if b.beat == 1],
                  "correccions": [], "bpm": a.tempo.bpm if a.tempo else None,
                  "compas": list(a.tempo.time_signature) if a.tempo else [4, 4], "desfasament": 0},
        "probabilitats": {"vores": beats + [a.source.duration_s], "etiquetes": [], "top": [[] for _ in beats]},
        "acords_audio": {"segs": segs},
        "lletra": {"font": a.lyrics_source, "asr": [], "correccions_asr": [], "paraules": paraules,
                   "linies": [list(l.word_range) for l in a.lines], "aparellades": None, "descartades": [],
                   "text": None},
        "fonts": None,
        "acords_fonts": {"segs": segs, "resum": None},
        "tonalitat": {"tonalitat": a.key.model_dump() if a.key else None, "capo": a.capo_suggerit},
        "estructura": {"elements": elements, "seccions": seccions, "content": content},
        "seccions_fonts": {"seccions": seccions, "content": content},
        "quadra": None,
        "final": {"elements": elements, "seccions": seccions, "content": content},
    })


def genera(clau: str, refes: bool = False) -> dict:
    t0 = time.perf_counter()
    o = origens.prepara(clau, refes)
    cfg = Config.carrega(None, lrclib=False)  # com tx bench; la lletra ja la porten les dades
    base = {
        "clau": clau, "origen": o.origen, "id": o.id, "titol": o.titol, "artista": o.artista,
        "youtube_id": o.youtube_id, "audio_local": o.audio is not None, "codi": codi(), "versio": __version__,
        "generat": time.strftime("%Y-%m-%d %H:%M:%S"), "avisos": o.avisos, "desada": net(o.desada),
        "info": net(o.info),
    }
    ref = o.referencia
    if o.dades is None:
        a = o.previa
        content = (o.desada or {}).get("content") or ""
        passos = _passos_de_analisi(a, content)
        return {**base, "nomes_analisi": True, "segons": round(time.perf_counter() - t0, 1), "passos": passos,
                "analisi": a.model_dump(mode="json"), "content": content, "sense_fonts": None,
                "referencia": net(_referencia(ref["content"] if ref else None, content, passos["final"]["elements"],
                                              a.words, a.capo_suggerit)),
                "metriques": None, "rodes": []}
    perfil = o.perfil or detecta("cpu")
    traca = Traca()
    res = executa(o.entrada, cfg, perfil, o.cache, dades=o.dades, previa=o.previa, traca=traca)
    sense = executa(o.entrada, cfg.model_copy(update={"fonts_acords": False}), perfil, o.cache, dades=o.dades,
                    previa=o.previa)
    a = res.analisi
    return {
        **base, "nomes_analisi": False, "segons": round(time.perf_counter() - t0, 1),
        "passos": traca.a_dict(),
        "analisi": a.model_dump(mode="json"),
        "content": res.content,
        "sense_fonts": {"content": sense.content, "capo": sense.analisi.capo_suggerit,
                        "acords": [c.model_dump(mode="json") for c in sense.analisi.chords],
                        "seccions": [s.model_dump(mode="json") for s in sense.analisi.sections]},
        "referencia": net(_referencia(ref["content"] if ref else None, res.content, res.elements, a.words,
                                      a.capo_suggerit)),
        "metriques": net(avalua(ref, res.content, a)) if ref else None,
        "rodes": net(_rodes(res.elements, traca.passos["final"]["seccions"])),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("clau", help="banc-<id>, web-<id>, local-<w|a>-<cache> o fitxer-<hash>")
    p.add_argument("--refes", action="store_true", help="La torna a calcular (i a baixar, si és de la web)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    clau = origens.normalitza_clau(args.clau)
    desti = cami_traca(clau)
    if desti.exists() and not args.refes:
        print(desti)
        return 0
    try:
        dades = genera(clau, args.refes)
    except origens.ErrorOrigen as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    desti.parent.mkdir(parents=True, exist_ok=True)
    for vella in desti.parent.glob("traca-*.json"):  # només en cal una per cançó
        vella.unlink()
    desti.write_text(json.dumps(dades, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(desti)
    return 0


if __name__ == "__main__":
    sys.exit(main())
