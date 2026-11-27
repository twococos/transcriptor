"""Depurador (depura/): d'on surten les cançons, el mode només anàlisi i la clau del play de l'app."""

import json

import numpy as np
import pytest

from transcriptor.depura import genera, origens, servidor
from transcriptor.schema import Acord, Font, Linia, Meta, Paraula, Pulsacio, Seccio, SongAnalysis, Tempo


def _analisi() -> SongAnalysis:
    beats = [Pulsacio(t=0.5 * i, bar=i // 4 + 1, beat=i % 4 + 1) for i in range(16)]
    paraules = [Paraula(start=1.0 + 0.5 * i, end=1.4 + 0.5 * i, text=w) for i, w in enumerate("hola que tal anem".split())]
    return SongAnalysis(source=Font(url="https://www.youtube.com/watch?v=abcdefghijk", youtube_id="abcdefghijk",
                                    duration_s=8.0),
                        meta=Meta(title="T", artist="A"), tempo=Tempo(bpm=120, time_signature=(4, 4)), beats=beats,
                        chords=[Acord(start=0.0, end=4.0, label="C", raw="C", conf=0.9),
                                Acord(start=4.0, end=8.0, label="G", raw="G", conf=0.8)],
                        words=paraules, lines=[Linia(start=1.0, end=2.9, word_range=(0, 4), section=0)],
                        sections=[Seccio(start=0.0, end=8.0, label="estrofa", name="Estrofa 1")])


@pytest.fixture
def entorn(monkeypatch, tmp_path):
    monkeypatch.setenv("TX_HOME", str(tmp_path))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)  # sense les caches de l'app de l'ordinador
    return tmp_path


def test_claus():
    assert origens.normalitza_clau("100") == "banc-100"
    assert origens.normalitza_clau("local:w-yt-abc") == "local-w-yt-abc"
    assert origens.normalitza_clau("local-w-yt-abc") == "local-w-yt-abc"
    with pytest.raises(origens.ErrorOrigen):
        origens.prepara("web-5")  # les cançons de la web es veuen al depurador del canconer


def test_fitxer_sense_cache_nomes_analisi(entorn):
    f = entorn / "out" / "analysis.json"
    f.parent.mkdir()
    f.write_text(_analisi().model_dump_json(), encoding="utf-8")
    (f.parent / "content.txt").write_text("<sec>Estrofa 1</sec>\n<ch>C</ch>hola que tal anem", encoding="utf-8")
    clau = servidor.clau_de(str(f.parent))  # el que fa el play de l'app amb el directori de la feta
    assert clau.startswith("fitxer-")
    t = genera.genera(clau)
    assert t["nomes_analisi"] and t["youtube_id"] == "abcdefghijk"
    assert t["content"].startswith("<sec>Estrofa 1</sec>")


def test_cache_local(entorn):
    d = entorn / "cache" / "yt-abcdefghijk"
    d.mkdir(parents=True)
    (d / "fetch.json").write_text(json.dumps({"url": "https://www.youtube.com/watch?v=abcdefghijk",
                                              "youtube_id": "abcdefghijk", "title": "Vídeo"}), encoding="utf-8")
    (d / "rhythm.json").write_text(json.dumps({"pulsacions": [0.5, 1.0], "inicis_compas": [0.5]}), encoding="utf-8")
    (d / "lyrics_asr.json").write_text(json.dumps({"paraules": [], "segments": []}), encoding="utf-8")
    (d / "chords_source.params.json").write_text(json.dumps({"titol": "T", "artista": "A", "urls": ["https://x/1"],
                                                             "bloquejades": [], "versio": 2}), encoding="utf-8")
    (d / "chords_source.json").write_text("[]", encoding="utf-8")
    np.savez_compressed(d / "chords.npz", probs=np.full((5, 170), 1 / 170, dtype=np.float32), per_trama=0.1)
    llista = origens.locals_()
    assert [x["clau"] for x in llista] == ["local-w-yt-abcdefghijk"]
    # Una feta de l'app d'aquesta cançó s'obre amb la cache, no només amb l'anàlisi
    feta = entorn / "fetes" / "3"
    feta.mkdir(parents=True)
    (feta / "analysis.json").write_text(_analisi().model_dump_json(), encoding="utf-8")
    assert servidor.clau_de(str(feta)) == "local-w-yt-abcdefghijk"
    o = origens.prepara("local-w-yt-abcdefghijk")
    # Títol, artista i tabs: els de la cerca de tabs, perquè es reaprofitin les baixades
    assert (o.entrada.titol, o.entrada.artista, o.entrada.urls_acords) == ("T", "A", ["https://x/1"])
    assert o.dades.fonts["params"]["titol"] == "T" and o.dades.lletra["font"] == "whisper"
