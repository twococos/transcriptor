"""Aplica les tabs a l'anàlisi: normalitza → alinea → consens → segona passada del Viterbi → grafia.

Sense tabs vàlides no es toca res (el resultat és exactament el de l'àudio sol).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import consens as consens_mod
from . import normalitza
from .alinea import Alineacio, Graella, alinea
from .model import TabCrua

log = logging.getLogger(__name__)


@dataclass
class ResultatFonts:
    segs: list[dict]  # segments d'acord finals (amb `raw`, `origen`, `fonts`)
    alineacions: list[Alineacio]  # les vàlides (amb pes)
    consens: consens_mod.Consens | None
    resum: dict = field(default_factory=dict)  # per a les estadístiques
    fonts: list[dict] = field(default_factory=list)  # per a SongAnalysis.chord_sources


def _etiqueta_a(segs: list[dict], t: float) -> str | None:
    for s in segs:
        if s["start"] <= t < s["end"]:
            return s.get("raw", s["label"])
    return None


def _origen(segs_audio: list[dict], segs: list[dict]) -> dict:
    """Marca cada segment final (audio | confirmat | substituit) i compta els canvis."""
    n = {"confirmats": 0, "substituits": 0, "afegits": 0, "trets": 0, "audio": 0}
    for s in segs:
        mig = (s["start"] + s["end"]) / 2
        abans = _etiqueta_a(segs_audio, mig)
        if abans != s["raw"]:
            s["origen"] = "substituit"
        elif s.get("fonts", 0) > 0.25:
            s["origen"] = "confirmat"
        else:
            s["origen"] = "audio"
        n[{"substituit": "substituits", "confirmat": "confirmats", "audio": "audio"}[s["origen"]]] += 1
    claus = {(round(s["start"], 1), s.get("raw", s["label"])) for s in segs}
    claus_audio = {(round(s["start"], 1), s["label"]) for s in segs_audio}
    n["afegits"] = max(0, len(segs) - len(segs_audio))
    n["trets"] = max(0, len(segs_audio) - len(segs))
    n["canvis_inici"] = len(claus - claus_audio)
    return n


def _mitjana(v: np.ndarray) -> float | None:
    v = v[~np.isnan(v)]
    return float(v.mean()) if len(v) else None


def _traca(traca, tabs: list[TabCrua], normals: list, alineacions: list, motius: dict, cons, g: Graella,
           fonts_info: list[dict]) -> None:
    """Desa per al depurador cada tab (normalitzada i alineada) i la bonificació del consens."""
    vores = g.vores
    llista = []
    for i, (crua, t, info) in enumerate(zip(tabs, normals, fonts_info)):
        al = alineacions[i]
        f = next((f for f in cons.fonts if f.al is al), None) if al is not None else None
        motiu = motius.get(i) or next((m for a, m in cons.descartades if a is al and al is not None), None)
        d = {**info, "motiu": motiu, "capo": crua.capo, "to": crua.to, "titol": crua.titol,
             "artista": crua.artista, "content": crua.content}
        if t is not None:
            d["linies"] = [{"text": l.text, "seccio": l.seccio, "repeticio": l.repeticio, "heretada": l.heretada,
                            "origen": l.origen, "acords": [[a.col, a.escrit] for a in l.acords]} for l in t.linies]
            d["seccions"] = [{"nom": s.nom, "tipus": s.tipus} for s in t.seccions]
        if al is not None:
            d["transport"] = al.transport
            d["acords"] = [{"idx": a.idx, "t": vores[a.inici], "fi": vores[a.fi], "escrit": a.escrit,
                            "etiqueta": g.etiquetes[a.k],
                            "linia": a.linia, "heretat": a.heretat,
                            "pes": _mitjana(al.pes_unitat[a.inici:a.fi]),
                            "plausible": _mitjana(al.plausible_unitat[a.inici:a.fi]),
                            "pes_consens": _mitjana(f.pes_unitat[a.inici:a.fi]) if f is not None else None}
                           for a in al.acords if a.fi > a.inici]
            d["linia_paraula"] = al.linia_paraula
        llista.append(d)
    bonificacio = None
    if cons.fonts:
        b = cons.bonificacio
        idx = np.argsort(-b, axis=1)[:, :3]
        bonificacio = [[[int(k), float(fila[k])] for k in ks if fila[k] > 0] for fila, ks in zip(b, idx)]
    traca.pas("fonts", tabs=llista, bonificacio=bonificacio, grups=cons.n_grups)


def aplica(tabs: list[TabCrua], g: Graella, segs_audio: list[dict],
           refes: Callable[[np.ndarray], list[dict]], traca=None) -> ResultatFonts:
    """`refes(bonificacio)` torna a passar el Viterbi amb la bonificació i retorna els segments.
    `traca` (traca.Traca, opcional): hi desa cada tab alineada i el consens, per al depurador."""
    alineacions, motius = [], []
    normals, motiu_de = [], {}
    for i, crua in enumerate(tabs):
        t = al = None
        try:
            t = normalitza.tab(crua)
            al = alinea(t, g)
        except Exception:  # noqa: BLE001 — una tab estranya no ha de fer fallar l'anàlisi
            log.warning("Font d'acords il·legible: %s", crua.url, exc_info=True)
            motius.append(f"{crua.lloc}: il·legible")
            motiu_de[i] = "il·legible"
        else:
            if al is None:
                motius.append(f"{crua.lloc}: no quadra amb la lletra")
                motiu_de[i] = "no quadra amb la lletra"
        normals.append(t)
        alineacions.append(al)
    fonts_info = []
    cons = consens_mod.calcula(alineacions, g)
    for crua, al in zip(tabs, alineacions):
        f = next((f for f in cons.fonts if f.al is al), None) if al is not None else None
        fonts_info.append({"site": crua.lloc, "url": crua.url, "rating": crua.valoracio, "votes": crua.vots,
                           "manual": crua.manual, "fit": round(al.encaix, 3) if al else None,
                           "matched": round(al.aparellades, 3) if al else None,
                           "weight": round(f.pes, 3) if f else 0.0, "group": f.grup if f else None,
                           "used": f is not None})
    if traca is not None:
        _traca(traca, tabs, normals, alineacions, motiu_de, cons, g, fonts_info)
    if not cons.fonts:
        return ResultatFonts(segs=segs_audio, alineacions=[], consens=None, fonts=fonts_info,
                             resum={"trobades": len(tabs), "valides": 0, "grups": 0})
    segs = refes(cons.bonificacio)
    for s in segs:
        s["raw"] = s["label"]
    consens_mod.grafia(segs, g.vores, cons, g.etiquetes)
    resum = {"trobades": len(tabs), "valides": len(cons.fonts), "grups": cons.n_grups, **_origen(segs_audio, segs)}
    return ResultatFonts(segs=segs, alineacions=[f.al for f in cons.fonts], consens=cons, resum=resum,
                         fonts=fonts_info)
