"""Cançons fetes desades en local (fetes.py) i progrés de la descàrrega de models."""

import json

from transcriptor import fetes
from transcriptor.models import EstatDescarrega, _classe_tqdm
from transcriptor.visor import inicia


def test_desa_llista_i_esborra(tmp_path, monkeypatch):
    monkeypatch.setenv("TX_HOME", str(tmp_path))
    analisi = json.dumps({"source": {"youtube_id": "abc"}})
    fetes.desa(1, {"title": "Bon dia", "artist": "Els Pets"}, analisi, None, 300)
    fetes.desa(2, {"title": "L'estaca", "artist": None}, analisi, tmp_path / "no-hi-es.wav", 61)
    llista = fetes.llista()
    assert [f.nom for f in llista] == ["L'estaca", "Bon dia — Els Pets"]  # la més recent primer
    assert not llista[0].te_audio and llista[0].segons == 61

    srv, url, _analisi, audio = inicia(llista[1].dir)  # sense àudio: el visor farà servir YouTube
    srv.server_close()
    assert audio is None and url.startswith("http://127.0.0.1:")

    fetes.esborra(llista[0])
    assert [f.titol for f in fetes.llista()] == ["Bon dia"]
    fetes.esborra_totes()
    assert fetes.llista() == []


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
