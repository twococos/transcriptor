"""Depurador (depura/): d'on surten les cançons i el mode només anàlisi."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from transcriptor.depura import genera, origens, web
from transcriptor.paquet import Crues, empaqueta
from transcriptor.schema import (Acord, Font, Linia, Meta, Paraula, Pulsacio, Seccio, SongAnalysis, Tempo,
                                 a_compacte)
from transcriptor.versions import VERSIO_ANALISI


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


def _crues() -> Crues:
    return Crues(meta={"url": "u"}, durada=10.0, ritme={"pulsacions": [0.5, 1.0], "inicis_compas": [0.5]},
                 probs=np.full((5, 170), 1 / 170, dtype=np.float32), per_trama=0.1,
                 asr={"paraules": [], "segments": []}, idioma_asr="ca", lletra=None, groove=None,
                 separador="htdemucs", compute_type="int8", versio=VERSIO_ANALISI)


CANCO = {"song_id": 7, "source_url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "T", "artist": "A",
         "language": "ca", "key": "C", "capo": 0, "state": 0, "song_content": "<sec>Estrofa</sec>\n<ch>C</ch>hola que tal anem",
         "song_content_human": True, "transcriber_content": "<ch>C</ch>hola", "chord_source_urls": ["https://x/1"],
         "chord_source_blocked": ["https://x/2"], "analysis_app_version": "0.1.15", "analyzed_at": "2026-11-15",
         "raw_app_version": VERSIO_ANALISI}


class Canconer:
    """El canconer simulat: GET /api/transcriber/songs/<id> amb un token."""

    def __init__(self, canco: dict):
        self.peticions = []
        servidor = self

        class Gestor(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                servidor.peticions.append(self.path)
                if self.headers.get("Authorization") != "Bearer secret":
                    return self._respon(401, {"error": "token"})
                if self.path == "/api/transcriber/songs/7":
                    return self._respon(200, canco)
                self._respon(404, {"error": "no"})

            def _respon(self, codi, dades):
                cos = json.dumps(dades).encode()
                self.send_response(codi)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cos)))
                self.end_headers()
                self.wfile.write(cos)

        self.http = HTTPServer(("127.0.0.1", 0), Gestor)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tanca(self):
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def entorn(monkeypatch, tmp_path):
    monkeypatch.setenv("TX_HOME", str(tmp_path))
    monkeypatch.setenv("TX_TOKEN", "secret")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)  # sense les caches de l'app de l'ordinador
    return tmp_path


def test_claus():
    assert origens.normalitza_clau("100") == "banc-100"
    assert origens.normalitza_clau("web:5") == "web-5"
    assert origens.normalitza_clau("local-w-yt-abc") == "local-w-yt-abc"


def test_web_com_el_worker(entorn, monkeypatch):
    canco = {**CANCO, "analysis": a_compacte(_analisi()), "raw": base64.b64encode(empaqueta(_crues())).decode()}
    s = Canconer(canco)
    monkeypatch.setenv("TX_API", s.url)
    try:
        o = origens.prepara("web-7")
    finally:
        s.tanca()
    # La mateixa entrada que una feina update del worker
    e = o.entrada
    assert (e.font, e.titol, e.artista, e.idioma) == (CANCO["source_url"], "T", "A", "ca")
    assert e.content_bd == CANCO["song_content"] and e.content_huma
    assert e.urls_acords == ["https://x/1"] and e.urls_bloquejades == ["https://x/2"]
    assert o.dades.ritme["pulsacions"] == [0.5, 1.0] and not o.avisos
    assert o.youtube_id == "abcdefghijk" and o.previa.meta.title == "T"
    assert o.referencia["content"] == CANCO["song_content"]
    assert o.desada["content"] == "<ch>C</ch>hola" and o.desada["analisi"]["chords"][1]["label"] == "G"
    # Sense xarxa, les dades baixades l'última vegada
    o2 = origens.prepara("web-7", refes=True)
    assert o2.dades.ritme == o.dades.ritme


def test_web_sense_dades_crues_mostra_l_analisi(entorn, monkeypatch):
    s = Canconer({**CANCO, "analysis": a_compacte(_analisi()), "raw": None})
    monkeypatch.setenv("TX_API", s.url)
    try:
        t = genera.genera("web-7")
    finally:
        s.tanca()
    assert t["nomes_analisi"] and t["avisos"]
    assert [c["label"] for c in t["passos"]["acords_fonts"]["segs"]] == ["C", "G"]
    assert t["passos"]["final"]["seccions"][0]["name"] == "Estrofa 1"
    assert t["referencia"]["acords"][0]["label"] == "C"  # «hola»
    json.dumps(t)


def test_web_token_rebutjat(entorn, monkeypatch):
    s = Canconer(CANCO)
    monkeypatch.setenv("TX_API", s.url)
    monkeypatch.setenv("TX_TOKEN", "dolent")
    try:
        with pytest.raises(origens.ErrorOrigen, match="token"):
            origens.prepara("web-7")
        with pytest.raises(web.ErrorWeb):
            web.canco(7)
    finally:
        s.tanca()


def test_fitxer_sense_cache_nomes_analisi(entorn):
    f = entorn / "out" / "analysis.json"
    f.parent.mkdir()
    f.write_text(_analisi().model_dump_json(), encoding="utf-8")
    (f.parent / "content.txt").write_text("<sec>Estrofa 1</sec>\n<ch>C</ch>hola que tal anem", encoding="utf-8")
    clau = origens.registra_fitxer(f.parent)
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
    o = origens.prepara("local-w-yt-abcdefghijk")
    # Títol, artista i tabs: els de la cerca de tabs, perquè es reaprofitin les baixades
    assert (o.entrada.titol, o.entrada.artista, o.entrada.urls_acords) == ("T", "A", ["https://x/1"])
    assert o.dades.fonts["params"]["titol"] == "T" and o.dades.lletra["font"] == "whisper"
    assert origens.registra_fitxer is not None
