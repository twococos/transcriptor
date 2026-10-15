"""Orquestració: fetch → separate → rhythm → chords → lyrics → postprocés → merge → structure → render.

Cada etapa cara es desa a la cache (cache.py). Els models es carreguen d'un en un i s'alliberen en
acabar cada etapa: el servidor va just de RAM.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import merge, render, structure
from .audio import durada as durada_audio
from .cache import Cache
from .config import Config, prepara_entorn_models
from .device import Perfil, configura_fils, detecta
from .notation import transposa
from .postprocess import chords_clean, key as key_mod, lines as lines_mod, meter
from .schema import (Acord, Font, ImportResult, Linia, Meta, Paraula, Pulsacio, Seccio, SongAnalysis,
                     Tempo, Tonalitat)
from .stages import chords, fetch, lyrics_align, lyrics_asr, lyrics_source, rhythm, separate
from .text import detecta_idioma, linies_de_text

log = logging.getLogger(__name__)

MIN_APARELLADES = 0.4  # per sota, la lletra i l'àudio probablement no són la mateixa versió


@dataclass
class Entrada:
    font: str  # URL o fitxer
    titol: str | None = None
    artista: str | None = None
    idioma: str | None = None  # None = el detecta Whisper
    text_usuari: str | None = None
    content_bd: str | None = None  # lletra de la BD (si la cançó ja hi és)


@dataclass
class Resultat:
    analisi: SongAnalysis
    content: str
    proposta: ImportResult
    elements: list[dict] = field(default_factory=list)


def _hash(text: str | None) -> str | None:
    return hashlib.sha1(text.encode()).hexdigest()[:12] if text else None


def _titol_artista(meta: dict, entrada: Entrada) -> tuple[str, str]:
    titol, artista = entrada.titol or "", entrada.artista or ""
    if not titol:
        t = meta.get("title", "")
        # Títols de YouTube habituals: "Artista - Títol (Videoclip oficial)"
        t = re.sub(r"\s*[\(\[][^)\]]*(oficial|official|video|videoclip|lyric|audio)[^)\]]*[\)\]]", "", t,
                   flags=re.I)
        if " - " in t:
            a, titol = (x.strip() for x in t.split(" - ", 1))
            artista = artista or a
        else:
            titol = t.strip()
    return titol, artista or meta.get("artist", "")


def executa(entrada: Entrada, cfg: Config | None = None, perfil: Perfil | None = None,
            cache: Cache | None = None) -> Resultat:
    cfg = cfg or Config()
    perfil = perfil or detecta("auto")
    configura_fils(perfil)
    dir_models = prepara_entorn_models()
    cache = cache or Cache(fetch.id_canco(entrada.font))
    inici_total = time.perf_counter()

    # Valors per defecte segons el dispositiu
    separador = cfg.separador or perfil.separador
    shifts = cfg.demucs_shifts if cfg.demucs_shifts is not None else perfil.demucs_shifts
    compute_type = cfg.whisper_compute_type or perfil.whisper_compute_type

    # 1. Àudio
    cami_audio = cache.cami("audio.wav")
    params_fetch = {"font": entrada.font}
    if not cami_audio.exists():
        cache.cami("fetch.params.json").unlink(missing_ok=True)
    meta = cache.json("fetch", params_fetch, lambda: fetch.descarrega(entrada.font, cami_audio))
    durada = durada_audio(cami_audio)
    titol, artista = _titol_artista(meta, entrada)

    # 2. Separació de la veu
    veu = cache.fitxer("separate", "vocals.wav", {"model": separador, "shifts": shifts},
                       lambda desti: separate.separa_veu(cami_audio, desti, perfil, separador, shifts,
                                                         dir_models))

    # 3. Ritme
    ritme = cache.json("rhythm", {"model": "beat_this-final0"}, lambda: rhythm.detecta(cami_audio, perfil))

    # 4. Acords (probabilitats per trama)
    def _calcula_acords(desti: Path) -> None:
        probs, per_trama = chords.probabilitats(cami_audio, perfil, dir_models)
        with open(desti, "wb") as f:
            np.savez_compressed(f, probs=probs, per_trama=per_trama)

    f_acords = cache.fitxer("chords", "chords.npz", {"model": "btc-large-voca"}, _calcula_acords)
    dades = np.load(f_acords)
    probs, per_trama = dades["probs"], float(dades["per_trama"])

    # 5. Text de la lletra
    font_lletra = cache.json(
        "lyrics_source",
        {"titol": titol, "artista": artista, "usuari": _hash(entrada.text_usuari),
         "bd": _hash(entrada.content_bd), "lrclib": cfg.lrclib, "versio": 3},
        lambda: dict(zip(("text", "font"), lyrics_source.obte(
            entrada.text_usuari, entrada.content_bd, titol, artista, durada, cfg.lrclib))),
    )

    # 6. ASR (sempre: dona els temps també quan tenim el text)
    # Idioma: explícit > deduït del text conegut > detecció de Whisper (de vegades falla: "Esperança"
    # es va detectar com a anglès perquè l'inici és instrumental)
    idioma_asr = entrada.idioma or (detecta_idioma(font_lletra["text"]) if font_lletra["text"] else None)
    asr = cache.json("lyrics_asr", {"model": cfg.whisper_model, "compute_type": compute_type,
                                    "idioma": idioma_asr, "veu": separador, "deteccio": 6,
                                    **({"vad": cfg.vad_llindar} if cfg.vad_llindar != 0.5 else {})},
                     lambda: lyrics_asr.transcriu(veu, perfil, cfg.whisper_model, compute_type, idioma_asr,
                                                  vad_llindar=cfg.vad_llindar))

    idioma = idioma_asr or asr.get("idioma") or "ca"

    # 7. Postprocés de ritme i acords
    t0 = time.perf_counter()
    etiquetes, col_lapse = chords_clean.vocabulari(cfg.acords_vocabulari)
    vores = chords_clean.unitats(ritme["pulsacions"], durada)
    p_unitat = chords_clean.probabilitats_per_unitat(probs, per_trama, vores, col_lapse)
    desfasament = 1 if len(vores) - 1 > len(ritme["pulsacions"]) else 0  # unitat [0, p0)
    canvis = chords_clean.canvis_crus(p_unitat)[desfasament:]
    compas = meter.regularitza(ritme["pulsacions"], ritme["inicis_compas"], canvis)
    inici_compas = np.array([False] * desfasament + [b["beat"] == 1 for b in compas["beats"]] + [False])
    cami = chords_clean.viterbi(p_unitat, inici_compas[: len(p_unitat)])
    min_unitats = max(1, int(round(cfg.acords_min_pulsacions)))
    segs = chords_clean.segments(cami, etiquetes, vores, p_unitat, min_unitats)

    tonalitat = key_mod.estima(segs)
    capo = key_mod.suggereix_capo(tonalitat) if (tonalitat and cfg.extra.get("aplicar_capo", True)) else 0

    # 8. Paraules i línies
    avisos: list[str] = []
    if font_lletra["text"]:
        lin_text = linies_de_text(font_lletra["text"])
        al = lyrics_align.alinea(lin_text, asr["paraules"], durada)
        paraules, rangs = al["paraules"], al["linies"]
        aparellades = al["aparellades"]
        if cfg.afinar_ctc and paraules:
            from .stages import lyrics_ctc

            clau = _hash(json.dumps([paraules, rangs], ensure_ascii=False))
            ctc = cache.json("lyrics_ctc", {"model": lyrics_ctc.MODEL, "entrada": clau},
                             lambda: dict(zip(("paraules", "afinades"),
                                              lyrics_ctc.afina(veu, paraules, rangs, perfil))))
            paraules = ctc["paraules"]
        if al["aparellades"] < MIN_APARELLADES:
            avisos.append(f"Només el {al['aparellades']:.0%} de la lletra coincideix amb el que es canta: "
                          "potser el vídeo no és la mateixa versió (o la lletra és d'una altra cançó)")
        if al["descartades"]:
            avisos.append(f"{len(al['descartades'])} línies de la lletra no es canten i s'han descartat: "
                          + " / ".join(al["descartades"][:6]))
    else:
        paraules = lines_mod.uneix_fragments(asr["paraules"])
        inicis = [b["t"] for b in compas["beats"] if b["beat"] == 1]
        rangs = lines_mod.talla(paraules, asr["segments"], inicis, cfg.pausa_linia_s, cfg.max_paraules_linia)
        aparellades = None
        font_lletra["font"] = "whisper"

    # 9. Fusió, estructura i render
    elements = merge.colloca(paraules, rangs, segs, compas["beats"], durada)
    durada_compas = merge._durada_compas(compas["beats"])
    seccions = structure.detecta(elements, durada, durada_compas)
    text_content = render.content(elements, seccions, capo)
    cache.temps["postproces"] = round(time.perf_counter() - t0, 1)

    # 10. Resultat
    idx_unitat_pulsacio = {u + desfasament: b for u, b in enumerate(compas["beats"])}
    acords_out = []
    for s in segs:
        b = idx_unitat_pulsacio.get(s["unitat"])
        acords_out.append(Acord(start=s["start"], end=s["end"], label=s["label"], raw=s["label"],
                                bar=b["bar"] if b else None, beat=b["beat"] if b else None, conf=s["conf"]))
    seccio_de_linia = {}
    for k, s in enumerate(seccions):
        for i in s["elements"]:
            seccio_de_linia[i] = k
    linies_out = [Linia(start=e["start"], end=e["end"], word_range=tuple(e["word_range"]),
                        section=seccio_de_linia.get(i))
                  for i, e in enumerate(elements) if e["tipus"] == "linia"]

    analisi = SongAnalysis(
        source=Font(url=meta.get("url"), youtube_id=meta.get("youtube_id"), fitxer=meta.get("fitxer"),
                    duration_s=round(durada, 2)),
        meta=Meta(title=titol, artist=artista, language=idioma),
        key=Tonalitat(**tonalitat) if tonalitat else None,
        capo_suggerit=capo,
        tempo=Tempo(bpm=compas["bpm"], time_signature=tuple(compas["time_signature"])),
        beats=[Pulsacio(**b) for b in compas["beats"]],
        chords=acords_out,
        words=[Paraula(**w) for w in paraules],
        lines=linies_out,
        sections=[Seccio(start=s["start"], end=s["end"], label=s["label"].lower(), name=s["name"])
                  for s in seccions],
        lyrics_source=font_lletra["font"],
        models={"separation": separador, "chords": "btc-large-voca", "rhythm": "beat_this-final0",
                "asr": f"faster-whisper-{cfg.whisper_model}-{compute_type}",
                "lyrics_align": "transfer-asr" if aparellades is not None else "cap",
                "device": perfil.device, "device_name": perfil.nom},
        temps_etapes_s={**cache.temps, "total": round(time.perf_counter() - inici_total, 1)},
        avisos=avisos,
    )
    clau_formes = key_mod.clau({"tonic": transposa(tonalitat["tonic"], -capo), "mode": tonalitat["mode"]}) \
        if tonalitat else "Am"
    proposta = ImportResult(title=titol, artist=artista, key=clau_formes, capo=capo, language=idioma,
                            content=text_content, youtubeUrl=meta.get("url"))
    if aparellades is not None:
        analisi.models["lyrics_aparellades"] = str(aparellades)
    return Resultat(analisi=analisi, content=text_content, proposta=proposta, elements=elements)
