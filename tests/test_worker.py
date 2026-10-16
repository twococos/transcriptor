"""Worker contra un servidor simulat (implementa el protocol de docs/api_worker.md)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from transcriptor import worker as worker_mod
from transcriptor.config import Config
from transcriptor.device import Perfil
from transcriptor.schema import Font, ImportResult, SongAnalysis

PERFIL = Perfil(device="cpu", nom="prova", vram_gb=0, fils=1, whisper_compute_type="int8",
                separador="htdemucs", demucs_shifts=0)


class Servidor:
    def __init__(self, feines, token="secret", min_version=None):
        self.feines = list(feines)
        self.token = token
        self.min_version = min_version
        self.peticions = []
        self.resultats = {}
        self.fallades = {}
        servidor = self

        class Gestor(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                cos = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)) or b"{}")
                servidor.peticions.append((self.path, cos))
                if self.headers.get("Authorization") != f"Bearer {servidor.token}":
                    return self._respon(401, {"error": "token"})
                if servidor.min_version:
                    return self._respon(426, {"min_version": servidor.min_version})
                if self.path == "/api/transcriber/claim":
                    if not servidor.feines:
                        return self._respon(204, None)
                    return self._respon(200, {"job": servidor.feines.pop(0)})
                id_feina = int(self.path.split("/")[4])
                if self.path.endswith("/result"):
                    servidor.resultats[id_feina] = cos
                elif self.path.endswith("/fail"):
                    servidor.fallades[id_feina] = cos
                return self._respon(200, {"ok": True})

            def _respon(self, codi, dades):
                self.send_response(codi)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if dades is not None:
                    self.wfile.write(json.dumps(dades).encode())

        self.http = HTTPServer(("127.0.0.1", 0), Gestor)
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tanca(self):
        self.http.shutdown()


def _resultat_fals(*_a, **_k):
    analisi = SongAnalysis(source=Font(duration_s=1.0))
    proposta = ImportResult(title="T", artist="A", key="Am", capo=0, language="ca", content="<sec>Estrofa 1</sec>")
    return type("R", (), {"analisi": analisi, "proposta": proposta})()


@pytest.fixture
def worker_fals(monkeypatch, tmp_path):
    monkeypatch.setenv("TX_HOME", str(tmp_path))
    monkeypatch.setattr(worker_mod, "id_canco", lambda font: "prova")

    def crea(servidor, token="secret", pipeline=_resultat_fals):
        monkeypatch.setattr(worker_mod, "executa", pipeline)
        client = worker_mod.Client(servidor.url, token, "test", PERFIL)
        return worker_mod.Worker(client, Config(), PERFIL)

    return crea


FEINA = {"id": 7, "source_url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "T", "artist": "A",
         "lease_seconds": 600}


def test_processa_una_feina_i_envia_el_resultat(worker_fals):
    s = Servidor([FEINA])
    try:
        w = worker_fals(s)
        w.bucle(una=True)
        assert 7 in s.resultats
        assert s.resultats[7]["proposal"]["key"] == "Am"
        assert s.resultats[7]["analysis"]["v"] == 2
        assert w.estat.fetes == 1
    finally:
        s.tanca()


def test_error_del_pipeline_es_reporta_com_a_fallada(worker_fals):
    s = Servidor([FEINA])

    def peta(*_a, **_k):
        raise RuntimeError("vídeo no disponible")

    try:
        w = worker_fals(s, pipeline=peta)
        w.bucle(una=True)
        assert "vídeo no disponible" in s.fallades[7]["error"]
        assert s.fallades[7]["released"] is False
        assert s.fallades[7]["kind"] == "temporary"
    finally:
        s.tanca()


def test_video_no_disponible_es_fallada_permanent(worker_fals):
    s = Servidor([FEINA])

    def peta(*_a, **_k):
        raise worker_mod.ErrorDescarrega("ERROR: [youtube] abc: Video unavailable", permanent=True)

    try:
        worker_fals(s, pipeline=peta).bucle(una=True)
        assert s.fallades[7]["kind"] == "permanent"
    finally:
        s.tanca()


def test_aturar_a_mitja_feina_l_allibera(worker_fals):
    s = Servidor([FEINA])

    def lent(*_a, **_k):
        w.atura.set()  # l'usuari desactiva el worker mentre processa
        return _resultat_fals()

    try:
        w = worker_fals(s, pipeline=lent)
        w.bucle()
        assert s.fallades[7]["released"] is True
        assert 7 not in s.resultats
    finally:
        s.tanca()


def test_token_revocat_i_versio_antiga(worker_fals):
    s = Servidor([FEINA])
    try:
        with pytest.raises(PermissionError):
            worker_fals(s, token="dolent").bucle(una=True)
    finally:
        s.tanca()
    s = Servidor([FEINA], min_version="9.9.9")
    try:
        with pytest.raises(worker_mod.VersioMassaAntiga):
            worker_fals(s).bucle(una=True)
    finally:
        s.tanca()


def test_cua_buida(worker_fals):
    s = Servidor([])
    try:
        w = worker_fals(s)
        w.bucle(una=True)
        assert w.estat.missatge == "Aturat" and w.estat.fetes == 0
    finally:
        s.tanca()


def test_aturar_interromp_el_pipeline_i_allibera_de_seguida(worker_fals):
    """L'aturada no espera que acabi la cançó: la feina s'allibera en un segon i el pipeline s'atura
    al següent punt de control."""
    import time

    s = Servidor([FEINA])
    alliberada_durant_el_calcul = []

    def llarg(*_a, comprova, **_k):
        threading.Timer(0.3, w.atura.set).start()
        inici = time.monotonic()
        while time.monotonic() - inici < 3:  # un càlcul llarg sense punts de control
            time.sleep(0.05)
        alliberada_durant_el_calcul.append(7 in s.fallades)
        while time.monotonic() - inici < 60:
            comprova()
            time.sleep(0.05)
        return _resultat_fals()

    try:
        w = worker_fals(s, pipeline=llarg)
        inici = time.monotonic()
        w.bucle()
        assert time.monotonic() - inici < 10
        assert alliberada_durant_el_calcul == [True]
        assert s.fallades[7]["released"] is True
        assert sum(p.endswith("/fail") for p, _ in s.peticions) == 1
        assert 7 not in s.resultats
    finally:
        s.tanca()
