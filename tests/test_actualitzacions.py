"""Actualització d'anàlisis antigues: versions (versions.py), paquet de dades crues (paquet.py) i
postprocés a partir de les dades crues, sense àudio (pipeline.executa amb `dades`)."""

import json
from pathlib import Path

import numpy as np

from transcriptor import versions
from transcriptor.cache import Cache
from transcriptor.config import Config
from transcriptor.device import Perfil
from transcriptor.paquet import Crues, desempaqueta, empaqueta
from transcriptor.pipeline import Entrada, executa
from transcriptor.schema import Font, Ritme, SongAnalysis

PERFIL = Perfil(device="cpu", nom="x", vram_gb=0, fils=1, whisper_compute_type="int8",
                separador="htdemucs", demucs_shifts=0)
RITME = json.loads((Path(__file__).parent / "dades" / "ritme" / "comedia.json").read_text(encoding="utf-8"))


def test_versions():
    assert versions.clau("0.1.10") > versions.clau("0.1.9")
    assert versions.clau(None) < versions.clau("0.0.1")
    assert versions.desactualitzada("0.1.7")
    assert not versions.desactualitzada(versions.VERSIO_ANALISI)
    # Des de la 0.1.7 cal l'àudio (l'estil és de la 0.1.8); des de la 0.1.8 n'hi ha prou amb el postprocés
    assert versions.crues_a_refer("0.1.7") == {"groove"}
    assert versions.crues_a_refer("0.1.8") == set()
    assert versions.crues_a_refer(None) == {"groove"}


def test_canvis_nomes_amb_etapes_conegudes():
    # Recordatori: cada entrada de CANVIS diu què canvia (postprocés o etapes crues de la cache)
    for etapes in versions.CANVIS.values():
        assert etapes <= versions.CRUES | {versions.POSTPROCES}


def _crues(amb_groove: bool = True) -> Crues:
    durada = 175.0
    trames = int(durada / 0.0929)
    rng = np.random.default_rng(0)
    probs = rng.dirichlet(np.full(170, 0.05), size=trames).astype(np.float32)
    groove = {"env": rng.random((3, int(durada * 86))).astype(np.float32) * 5, "planor": 0.12} if amb_groove else None
    return Crues(meta={"url": "https://www.youtube.com/watch?v=x", "youtube_id": "x", "title": "T", "artist": "A"},
                 durada=durada, ritme=RITME, probs=probs, per_trama=0.0929,
                 asr={"paraules": [], "segments": [], "idioma": "ca"}, idioma_asr="ca",
                 lletra={"text": None, "font": "cap"}, groove=groove, separador="htdemucs",
                 compute_type="int8", versio="0.1.9")


def test_paquet_anada_i_tornada():
    c = _crues()
    b = empaqueta(c)
    d = desempaqueta(b)
    assert (d.meta, d.ritme, d.asr, d.versio, d.durada) == (c.meta, c.ritme, c.asr, c.versio, c.durada)
    assert d.probs.shape == c.probs.shape
    assert np.abs(d.probs - np.where(c.probs < 1e-3, 0, c.probs)).max() < 0.01
    assert np.abs(d.groove["env"] - c.groove["env"]).max() <= c.groove["env"].max() / 255
    assert desempaqueta(empaqueta(_crues(amb_groove=False))).groove is None


def test_postproces_des_de_les_dades_crues(tmp_path):
    previa = SongAnalysis(source=Font(duration_s=175.0), rhythm=Ritme(style="rumba", confidence=0.6))
    entrada = Entrada(font="https://www.youtube.com/watch?v=x")
    cfg = Config(lrclib=False)

    r = executa(entrada, cfg, PERFIL, Cache("x", base=tmp_path), dades=_crues(amb_groove=False), previa=previa)
    assert len(r.analisi.beats) > 400
    assert r.analisi.rhythm.style == "rumba"  # sense envolupants es manté l'estil anterior
    assert r.crues is not None

    r2 = executa(entrada, cfg, PERFIL, Cache("x", base=tmp_path), dades=desempaqueta(empaqueta(r.crues)),
                 previa=previa)
    assert [b.t for b in r2.analisi.beats] == [b.t for b in r.analisi.beats]
