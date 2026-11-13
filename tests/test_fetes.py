"""Cançons fetes desades en local (fetes.py) i progrés de la descàrrega de models."""

import json
import threading
import urllib.request

from transcriptor import fetes
from transcriptor.models import EstatDescarrega, _classe_tqdm
from transcriptor.visor import inicia


def test_desa_llista_i_esborra(tmp_path, monkeypatch):
    monkeypatch.setenv("TX_HOME", str(tmp_path))
    analisi = json.dumps({"source": {"youtube_id": "abc"}})
    fetes.desa(1, {"title": "Bon dia", "artist": "Els Pets"}, analisi, 300)
    fetes.desa(2, {"title": "L'estaca", "artist": None}, analisi, 61)
    llista = fetes.llista()
    assert [f.nom for f in llista] == ["L'estaca", "Bon dia — Els Pets"]  # la més recent primer
    assert llista[0].segons == 61
    assert sorted(f.name for f in llista[0].dir.iterdir()) == ["analysis.json", "info.json"]  # sense àudio

    srv, url, _analisi, audio = inicia(llista[1].dir)  # el visor farà servir YouTube
    srv.server_close()
    assert audio is None and url.startswith("http://127.0.0.1:")

    fetes.esborra(llista[0])
    assert [f.titol for f in fetes.llista()] == ["Bon dia"]
    fetes.esborra_totes()
    assert fetes.llista() == []


def test_esborra_audios_vells(tmp_path, monkeypatch):
    monkeypatch.setenv("TX_HOME", str(tmp_path))
    assert fetes.esborra_audios_vells() == 0  # encara no hi ha cap cançó
    d = fetes.desa(1, {"title": "Bon dia"}, json.dumps({}), 300)
    (d / "audio.opus").write_bytes(b"x" * 100)  # el que desaven les versions anteriors a la 0.1.12
    assert fetes.esborra_audios_vells() == 1
    assert not (d / "audio.opus").exists() and [f.titol for f in fetes.llista()] == ["Bon dia"]


def test_visor_prefereix_youtube(tmp_path):
    audio = tmp_path / "canco.mp3"
    audio.write_bytes(b"x")
    analisi = tmp_path / "analysis.json"

    def info(**kw) -> dict:
        srv, url, _a, _au = inicia(analisi, **kw)
        try:
            threading.Thread(target=srv.handle_request, daemon=True).start()
            with urllib.request.urlopen(url + "info.json", timeout=5) as r:
                return json.loads(r.read())
        finally:
            srv.server_close()

    analisi.write_text(json.dumps({"source": {"youtube_id": "abc", "fitxer": str(audio)}}), encoding="utf-8")
    assert info() == {"audio": "canco.mp3", "prefereix_audio": False, "json": str(analisi)}  # de reserva
    assert info(audio=audio)["prefereix_audio"] is True  # tx visor --audio


def test_progres_compta_nomes_els_bytes_baixats():
    e = EstatDescarrega(total=1000, n=2, mida_pas=600)
    tqdm = _classe_tqdm(e)
    tqdm(unit="B", desc="Downloading bytes", total=0).update(250)
    tqdm(unit="B", desc="Reconstructing (incomplete total...)", total=0).update(250)  # els mateixos bytes
    tqdm(desc="Fetching 4 files", total=4).update(1)  # fitxers, no bytes
    assert e.bytes() == 250
    e.rebut_pas = 10_000  # mai més del que s'espera del pas
    assert e.bytes() == 600
    e.acabat = True
    assert e.bytes() == 1000
