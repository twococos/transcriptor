"""Visor de sincronització: reprodueix la cançó i mostra en directe pulsació, compàs, paraula i acord.

Serveix una pàgina local (visor.html) amb l'`analysis.json` i, si n'hi ha, l'àudio. Sense àudio local
fa servir el vídeo de YouTube de `source.youtube_id` (l'iframe de YouTube no funciona des de file://,
per això cal el servidor).
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger(__name__)

PAGINA = Path(__file__).with_name("visor.html")


def troba_audio(analisi: dict, json_path: Path) -> Path | None:
    """L'àudio d'origen si encara és al disc (bench: work/bench/audio/<id>.*)."""
    fitxer = (analisi.get("source") or {}).get("fitxer")
    if fitxer and Path(fitxer).is_file():
        return Path(fitxer)
    for f in json_path.parent.glob("audio.*"):
        return f
    return None


def _handler(json_path: Path, audio: Path | None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # sense soroll a la consola
            log.debug(fmt, *args)

        def _envia(self, dades: bytes, tipus: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", tipus)
            self.send_header("Content-Length", str(len(dades)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(dades)

        def _audio(self) -> None:
            # Range és imprescindible: sense, el navegador no deixa saltar enrere/endavant
            mida = audio.stat().st_size
            inici, fi = 0, mida - 1
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if m:
                if m.group(1):
                    inici = int(m.group(1))
                    fi = int(m.group(2)) if m.group(2) else fi
                elif m.group(2):
                    inici = mida - int(m.group(2))
                fi = min(fi, mida - 1)
            self.send_response(206 if m else 200)
            self.send_header("Content-Type", mimetypes.guess_type(audio.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(fi - inici + 1))
            if m:
                self.send_header("Content-Range", f"bytes {inici}-{fi}/{mida}")
            self.end_headers()
            if self.command == "HEAD":
                return
            with audio.open("rb") as f:
                f.seek(inici)
                resta = fi - inici + 1
                while resta > 0:
                    bloc = f.read(min(1 << 16, resta))
                    if not bloc:
                        break
                    try:
                        self.wfile.write(bloc)
                    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                        return  # el navegador talla la petició quan salta
                    resta -= len(bloc)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            ruta = self.path.split("?")[0]
            if ruta in ("/", "/index.html"):
                self._envia(PAGINA.read_bytes(), "text/html; charset=utf-8")
            elif ruta == "/analysis.json":
                self._envia(json_path.read_bytes(), "application/json; charset=utf-8")
            elif ruta == "/info.json":
                info = {"audio": audio.name if audio else None, "json": str(json_path)}
                self._envia(json.dumps(info, ensure_ascii=False).encode("utf-8"), "application/json")
            elif ruta == "/audio" and audio:
                self._audio()
            else:
                self.send_error(404)

    return H


def serveix(cami: str, audio: str | None = None, port: int = 8765, obre: bool = True) -> int:
    json_path = Path(cami)
    if json_path.is_dir():
        json_path = json_path / "analysis.json"
    if not json_path.is_file():
        print(f"No trobo {json_path}")
        return 1
    analisi = json.loads(json_path.read_text(encoding="utf-8"))
    fitxer_audio = Path(audio) if audio else troba_audio(analisi, json_path)
    if fitxer_audio and not fitxer_audio.is_file():
        print(f"No trobo l'àudio {fitxer_audio}")
        return 1

    srv = ThreadingHTTPServer(("127.0.0.1", port), _handler(json_path, fitxer_audio))
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    font = fitxer_audio or (f"YouTube {analisi['source']['youtube_id']}"
                            if analisi.get("source", {}).get("youtube_id") else "cap (arrossega'n un a la pàgina)")
    print(f"Visor: {url}\n  anàlisi: {json_path}\n  àudio:   {font}\n(Ctrl+C per aturar)")
    if obre:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
