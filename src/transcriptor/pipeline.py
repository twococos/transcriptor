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
from typing import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import __version__, estadistiques, merge, render, structure
from .audio import durada as durada_audio
from .cache import Cache
from .config import Config, prepara_entorn_models
from .device import Perfil, configura_fils, detecta
from .notation import transposa
from .paquet import Crues
from .postprocess import chords_clean, key as key_mod, lines as lines_mod, meter, pulsacions as pulsacions_mod
from .postprocess import style as style_mod
from .schema import (Acord, Font, Groove, ImportResult, Linia, Meta, Paraula, Pulsacio, Ritme, Seccio,
                     SongAnalysis, Tempo, Tonalitat)
from .stages import chords, fetch, groove, lyrics_align, lyrics_asr, lyrics_source, rhythm, separate
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
    estadistiques: dict = field(default_factory=dict)  # vegeu estadistiques.py
    crues: Crues | None = None  # dades crues (paquet.py), per enviar-les amb el resultat


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


def _estil(envs: dict | None, compas: dict, previa: Ritme | None) -> Ritme | None:
    """Estil rítmic de l'acompanyament (per al reproductor del canconer). Mai fa fallar la feina.

    Sense envolupants (dades crues d'una cache local sense àudio) es manté el de l'anàlisi anterior."""
    if envs is None:
        return previa
    try:
        emp = groove.de_envolupants(envs, compas["beats"], compas["time_signature"])
        if not emp:
            return None
        c = style_mod.classifica(emp, compas["bpm"], compas["time_signature"])
        return Ritme(style=c["style"], confidence=c["confidence"],
                     alternatives=[tuple(a) for a in c["alternatives"]],
                     groove=Groove(slots_per_beat=emp["slots_per_beat"], low=emp["low"], mid=emp["mid"],
                                   high=emp["high"]))
    except Exception:  # noqa: BLE001 — l'estil és un extra: sense ell, la resta de l'anàlisi serveix
        log.warning("No s'ha pogut detectar l'estil rítmic", exc_info=True)
        return None


def ritme_i_acords(ritme: dict, probs: np.ndarray, per_trama: float, durada: float,
                   cfg: Config) -> tuple[list[dict], dict, list[dict], int]:
    """Pulsacions corregides → compàs → acords per pulsació (també el fa servir tools/revisa_ritme.py).

    Retorna (correccions de la graella, compàs de meter.regularitza, segments d'acord, desfasament)."""
    corr = pulsacions_mod.corregeix(ritme["pulsacions"], ritme["inicis_compas"])
    pulsacions = corr["pulsacions"]
    etiquetes, col_lapse = chords_clean.vocabulari(cfg.acords_vocabulari)
    vores = chords_clean.unitats(pulsacions, durada)
    p_unitat = chords_clean.probabilitats_per_unitat(probs, per_trama, vores, col_lapse)
    desfasament = 1 if len(vores) - 1 > len(pulsacions) else 0  # unitat [0, p0)
    canvis = chords_clean.canvis_crus(p_unitat)[desfasament:]
    compas = meter.regularitza(pulsacions, corr["inicis_compas"], canvis)
    inici_compas = np.array([False] * desfasament + [b["beat"] == 1 for b in compas["beats"]] + [False])
    cami = chords_clean.viterbi(p_unitat, inici_compas[: len(p_unitat)])
    min_unitats = max(1, int(round(cfg.acords_min_pulsacions)))
    segs = chords_clean.segments(cami, etiquetes, vores, p_unitat, min_unitats)
    return corr["correccions"], compas, segs, desfasament


# Fases que veu l'usuari a l'app (en_fase); l'ordre és el de l'execució
FASES = [
    "Baixant l'àudio",
    "Separant la veu de l'acompanyament",
    "Detectant el ritme i el compàs",
    "Reconeixent els acords",
    "Buscant la lletra",
    "Desxifrant la lletra",
    "Sincronitzant la lletra amb la música",
    "Muntant la cançó",
]


class SenseDadesCrues(Exception):
    """A la cache local hi falta alguna etapa crua i no es pot calcular sense l'àudio."""


def crues(entrada: Entrada, cfg: Config, perfil: Perfil, cache: Cache, fase: Callable[[int], None],
          comprova: Callable[[], None] | None, sense_audio: bool = False,
          durada: float | None = None) -> tuple[Crues, Path | None]:
    """Fases 1–6: la sortida dels models i de l'àudio (cada etapa, de la cache si hi és).

    Amb `sense_audio` només es fa servir el que ja és a la cache (cal `durada`): si hi falta alguna
    etapa, SenseDadesCrues. Les envolupants de l'estil poden faltar (l'estil es manté l'anterior).
    Retorna també el camí de la veu separada, si n'hi ha (per a l'afinament CTC opcional)."""
    dir_models = prepara_entorn_models()
    separador = cfg.separador or perfil.separador
    shifts = cfg.demucs_shifts if cfg.demucs_shifts is not None else perfil.demucs_shifts
    compute_type = cfg.whisper_compute_type or perfil.whisper_compute_type

    def de_la_cache(etapa: str, params: dict):
        valor = cache.llegeix(etapa, params)
        if valor is None:
            raise SenseDadesCrues(etapa)
        return valor

    # 1. Àudio
    fase(0)
    cami_audio = cache.cami("audio.wav")
    params_fetch = {"font": entrada.font}
    if sense_audio:
        meta = de_la_cache("fetch", params_fetch)
    else:
        if not cami_audio.exists():
            cache.cami("fetch.params.json").unlink(missing_ok=True)
        meta = cache.json("fetch", params_fetch, lambda: fetch.descarrega(entrada.font, cami_audio))
        durada = durada_audio(cami_audio)
    titol, artista = _titol_artista(meta, entrada)

    # 2. Separació de la veu
    fase(1)
    veu = None if sense_audio else cache.fitxer(
        "separate", "vocals.wav", {"model": separador, "shifts": shifts},
        lambda desti: separate.separa_veu(cami_audio, desti, perfil, separador, shifts, dir_models, comprova))

    # 3. Ritme
    fase(2)
    params_ritme = {"model": "beat_this-final0"}
    if sense_audio:
        ritme = de_la_cache("rhythm", params_ritme)
    else:
        ritme = cache.json("rhythm", params_ritme, lambda: rhythm.detecta(cami_audio, perfil))

    # 4. Acords (probabilitats per trama)
    fase(3)
    def _calcula_acords(desti: Path) -> None:
        probs, per_trama = chords.probabilitats(cami_audio, perfil, dir_models)
        with open(desti, "wb") as f:
            np.savez_compressed(f, probs=probs, per_trama=per_trama)

    params_acords = {"model": "btc-large-voca"}
    if sense_audio:
        f_acords = cache.existent("chords", "chords.npz", params_acords)
        if f_acords is None:
            raise SenseDadesCrues("chords")
    else:
        f_acords = cache.fitxer("chords", "chords.npz", params_acords, _calcula_acords)
    dades = np.load(f_acords)
    probs, per_trama = dades["probs"], float(dades["per_trama"])

    # 5. Text de la lletra (no necessita l'àudio)
    fase(4)
    font_lletra = _font_lletra(cache, entrada, cfg, titol, artista, durada)

    # 6. ASR (sempre: dona els temps també quan tenim el text)
    fase(5)
    # Idioma: explícit > deduït del text conegut > detecció de Whisper (de vegades falla: "Esperança"
    # es va detectar com a anglès perquè l'inici és instrumental)
    idioma_asr = entrada.idioma or (detecta_idioma(font_lletra["text"]) if font_lletra["text"] else None)
    params_asr = {"model": cfg.whisper_model, "compute_type": compute_type, "idioma": idioma_asr,
                  "veu": separador, "deteccio": 6,
                  **({"vad": cfg.vad_llindar} if cfg.vad_llindar != 0.5 else {})}
    if sense_audio:
        asr = de_la_cache("lyrics_asr", params_asr)
    else:
        asr = cache.json("lyrics_asr", params_asr,
                         lambda: lyrics_asr.transcriu(veu, perfil, cfg.whisper_model, compute_type, idioma_asr,
                                                      vad_llindar=cfg.vad_llindar, comprova=comprova))

    # Envolupants de l'acompanyament, per a l'estil
    params_groove = {"env": 1, "veu": separador}
    if sense_audio:
        f_groove = cache.existent("groove", "groove_env.npz", params_groove)
    else:
        def _calcula_groove(desti: Path) -> None:
            e = groove.envolupants_de_fitxers(cami_audio, veu)
            with open(desti, "wb") as f:
                np.savez_compressed(f, env=e["env"], planor=e["planor"])

        try:
            f_groove = cache.fitxer("groove", "groove_env.npz", params_groove, _calcula_groove)
        except Exception:  # noqa: BLE001 — l'estil és un extra: sense ell, la resta de l'anàlisi serveix
            log.warning("No s'han pogut calcular les envolupants de l'estil", exc_info=True)
            f_groove = None
    envs = None
    if f_groove is not None:
        g = np.load(f_groove)
        envs = {"env": g["env"], "planor": float(g["planor"])}

    return Crues(meta=meta, durada=float(durada), ritme=ritme, probs=probs, per_trama=per_trama, asr=asr,
                 idioma_asr=idioma_asr, lletra=font_lletra, groove=envs, separador=separador,
                 compute_type=compute_type, versio=__version__), veu


def _font_lletra(cache: Cache, entrada: Entrada, cfg: Config, titol: str, artista: str, durada: float) -> dict:
    return cache.json(
        "lyrics_source",
        {"titol": titol, "artista": artista, "usuari": _hash(entrada.text_usuari),
         "bd": _hash(entrada.content_bd), "lrclib": cfg.lrclib, "versio": 3},
        lambda: dict(zip(("text", "font"), lyrics_source.obte(
            entrada.text_usuari, entrada.content_bd, titol, artista, durada, cfg.lrclib))),
    )


def executa(entrada: Entrada, cfg: Config | None = None, perfil: Perfil | None = None,
            cache: Cache | None = None, en_fase: Callable[[int, str], None] | None = None,
            comprova: Callable[[], None] | None = None, dades: Crues | None = None,
            previa: SongAnalysis | None = None, sense_audio: bool = False) -> Resultat:
    """`en_fase(i, nom)` es crida en començar cada fase (índex dins FASES).

    `comprova()` es crida sovint (entre fases i dins les llargues) i llança una excepció si s'ha
    d'aturar la feina.

    Per actualitzar una anàlisi (feina `update`, vegeu versions.py): amb `dades` (paquet de dades
    crues) només es fa el postprocés; amb `sense_audio`, les dades crues surten de la cache local o
    SenseDadesCrues. `previa` és l'anàlisi que s'actualitza: se'n conserva l'estil si no hi ha
    envolupants de l'acompanyament."""
    cfg = cfg or Config()

    def fase(i: int) -> None:
        if comprova:
            comprova()
        if en_fase:
            en_fase(i, FASES[i])

    perfil = perfil or detecta("auto")
    configura_fils(perfil)
    cache = cache or Cache(fetch.id_canco(entrada.font))
    inici_total = time.perf_counter()

    veu = None
    if dades is None:
        durada_previa = previa.source.duration_s if previa else None
        dades, veu = crues(entrada, cfg, perfil, cache, fase, comprova, sense_audio, durada_previa)
    c = dades
    titol, artista = _titol_artista(c.meta, entrada)
    durada = c.durada
    asr = c.asr
    if c.lletra is None or entrada.text_usuari or entrada.content_bd:
        # La lletra de la BD pot haver canviat des que es van fer les dades crues: la d'ara mana
        font_lletra = _font_lletra(cache, entrada, cfg, titol, artista, durada)
    else:
        font_lletra = dict(c.lletra)
    idioma = c.idioma_asr or asr.get("idioma") or "ca"
    separador, compute_type = c.separador, c.compute_type

    # 7. Postprocés de ritme i acords
    fase(6)
    t0 = time.perf_counter()
    correccions_ritme, compas, segs, desfasament = ritme_i_acords(c.ritme, c.probs, c.per_trama, durada, cfg)

    tonalitat = key_mod.estima(segs)
    capo = key_mod.suggereix_capo(tonalitat) if (tonalitat and cfg.extra.get("aplicar_capo", True)) else 0

    ritme_estil = _estil(c.groove, compas, previa.rhythm if previa else None)

    # 8. Paraules i línies
    avisos: list[str] = []
    al: dict | None = None
    if font_lletra["text"]:
        lin_text = linies_de_text(font_lletra["text"])
        al = lyrics_align.alinea(lin_text, asr["paraules"], durada)
        paraules, rangs = al["paraules"], al["linies"]
        aparellades = al["aparellades"]
        if cfg.afinar_ctc and paraules and veu is not None:
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
    fase(7)
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
        source=Font(url=c.meta.get("url"), youtube_id=c.meta.get("youtube_id"), fitxer=c.meta.get("fitxer"),
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
        rhythm=ritme_estil,
        lyrics_source=font_lletra["font"],
        models={"separation": separador, "chords": "btc-large-voca", "rhythm": "beat_this-final0",
                "style": f"plantilles-v{groove.VERSIO}",
                "asr": f"faster-whisper-{cfg.whisper_model}-{compute_type}",
                "lyrics_align": "transfer-asr" if aparellades is not None else "cap",
                "rhythm_fixes": str(len(correccions_ritme)),
                "device": perfil.device, "device_name": perfil.nom},
        temps_etapes_s={**cache.temps, "total": round(time.perf_counter() - inici_total, 1)},
        avisos=avisos,
    )
    clau_formes = key_mod.clau({"tonic": transposa(tonalitat["tonic"], -capo), "mode": tonalitat["mode"]}) \
        if tonalitat else "Am"
    proposta = ImportResult(title=titol, artist=artista, key=clau_formes, capo=capo, language=idioma,
                            content=text_content, youtubeUrl=c.meta.get("url"))
    if aparellades is not None:
        analisi.models["lyrics_aparellades"] = str(aparellades)
    stats = estadistiques.calcula(analisi, perfil, cache.cached, al,
                                  [w["conf"] for w in asr["paraules"] if w.get("conf") is not None],
                                  cfg.acords_vocabulari)
    return Resultat(analisi=analisi, content=text_content, proposta=proposta, elements=elements,
                    estadistiques=stats, crues=c)
