"""Servidor del depurador (`tx depura`): serveix depura.html i l'API de traces.

La traça es calcula en un subprocés amb el codi actual i es desa per hash del codi: després de
canviar el postprocés, n'hi ha prou amb recarregar la cançó (no cal reiniciar el servidor).

Rutes:
- `/`: la pàgina.
- `/api/config`: què hi ha en aquest ordinador (`{banc}`: si hi ha el banc de proves).
- `/api/runs`: les execucions del banc.
- `/api/cancons?run=&compara=`: les cançons del banc amb les mètriques de dos runs.
- `/api/locals`: les caches locals (origens.locals_).
- `/api/traca/<clau>[?refes=1]`: la traça (vegeu genera.py per a les claus).
- `/api/run/<nom>/<id>`: l'anàlisi i el content d'una execució desada del banc.
- `/api/notes/<clau>`: GET i POST.
- `/audio/<clau>`: l'àudio local, si n'hi ha.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from ..visor import envia_audio
from . import genera, origens

log = logging.getLogger(__name__)

PAGINA = Path(__file__).with_name("depura.html")
RESULTATS = Path("work/bench/resultats")
RE_CLAU = re.compile(r"^(banc-\d+|local-[wa]-[\w.-]+|fitxer-[0-9a-f]+)$")

_bloquejos: dict[str, threading.Lock] = {}
_bloqueig_global = threading.Lock()


def _bloqueig(clau: str) -> threading.Lock:
    with _bloqueig_global:
        return _bloquejos.setdefault(clau, threading.Lock())


def runs() -> list[str]:
    """Execucions del banc, de la més recent a la més antiga."""
    if not RESULTATS.is_dir():
        return []
    dirs = [d for d in RESULTATS.iterdir() if (d / "resultats.csv").exists()]
    return [d.name for d in sorted(dirs, key=lambda d: (d / "resultats.csv").stat().st_mtime, reverse=True)]


def _files(run: str | None) -> dict[int, dict]:
    if not run or "/" in run or "\\" in run:
        return {}
    f = RESULTATS / run / "resultats.csv"
    if not f.exists():
        return {}
    with open(f, encoding="utf-8") as fh:
        return {int(r["id"]): r for r in csv.DictReader(fh) if r.get("id", "").isdigit()}


def cancons(run: str | None, compara: str | None) -> dict:
    hash_codi = genera.codi()
    a, b = _files(run), _files(compara)
    llista = []
    for c in origens.dataset():
        llista.append({"clau": f"banc-{c['id']}", "id": c["id"], "titol": c["title"], "artista": c["artist"],
                       "estat": c["state"], "audio": origens.audio_de(c["id"]) is not None,
                       "traca": genera.cami_traca(f"banc-{c['id']}", hash_codi).exists(),
                       "run": a.get(c["id"]), "compara": b.get(c["id"])})
    return {"cancons": llista, "codi": hash_codi}


def traca(clau: str, refes: bool) -> tuple[int, bytes]:
    """(estat HTTP, JSON). Genera la traça en un subprocés si no hi és per al codi actual."""
    with _bloqueig(clau):
        desti = genera.cami_traca(clau)
        if refes or not desti.exists():
            ordre = [sys.executable, "-m", "transcriptor.depura.genera", clau] + (["--refes"] if refes else [])
            p = subprocess.run(ordre, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            if p.returncode != 0:
                linies = (p.stderr or p.stdout).strip().splitlines()
                error = next((l[7:] for l in reversed(linies) if l.startswith("ERROR: ")), None)
                return 500, json.dumps({"error": error or "\n".join(linies[-30:])}, ensure_ascii=False).encode("utf-8")
            desti = Path(p.stdout.strip().splitlines()[-1])
        return 200, desti.read_bytes()


def run_canco(nom: str, id_c: int) -> dict | None:
    d = RESULTATS / nom / str(id_c)
    if "/" in nom or "\\" in nom or not (d / "analysis.json").exists():
        return None
    content = d / "content.txt"
    return {"nom": f"Run «{nom}»", "analisi": json.loads((d / "analysis.json").read_text(encoding="utf-8")),
            "content": content.read_text(encoding="utf-8") if content.exists() else ""}


def _notes_fitxer() -> Path:
    return origens.dir_traces() / "notes.json"


def notes() -> dict:
    f = _notes_fitxer()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def desa_notes(clau: str, llista: list) -> None:
    with _bloqueig("notes"):
        totes = notes()
        totes[clau] = llista
        if not llista:
            del totes[clau]
        f = _notes_fitxer()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(totes, ensure_ascii=False, indent=1), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # sense soroll a la consola
        log.debug(fmt, *args)

    def _envia(self, dades: bytes, tipus: str = "application/json; charset=utf-8", estat: int = 200) -> None:
        self.send_response(estat)
        self.send_header("Content-Type", tipus)
        self.send_header("Content-Length", str(len(dades)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(dades)

    def _json(self, obj, estat: int = 200) -> None:
        self._envia(json.dumps(obj, ensure_ascii=False).encode("utf-8"), estat=estat)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        parts = [p for p in url.path.split("/") if p]
        try:
            if not parts or parts == ["index.html"]:
                self._envia(PAGINA.read_bytes(), "text/html; charset=utf-8")
            elif parts == ["api", "config"]:
                self._json({"banc": origens.DATASET.exists()})
            elif parts == ["api", "runs"]:
                self._json(runs())
            elif parts == ["api", "cancons"]:
                self._json(cancons(q.get("run"), q.get("compara")))
            elif parts == ["api", "locals"]:
                self._json(origens.locals_())
            elif len(parts) == 3 and parts[:2] == ["api", "traca"] and RE_CLAU.match(parts[2]):
                estat, dades = traca(parts[2], q.get("refes") == "1")
                self._envia(dades, estat=estat)
            elif len(parts) == 4 and parts[:2] == ["api", "run"] and parts[3].isdigit():
                r = run_canco(parts[2], int(parts[3]))
                self._json(r if r else {"error": "no hi és"}, 200 if r else 404)
            elif len(parts) == 3 and parts[:2] == ["api", "notes"] and RE_CLAU.match(parts[2]):
                self._json(notes().get(parts[2], []))
            elif len(parts) == 2 and parts[0] == "audio" and RE_CLAU.match(parts[1]):
                audio = origens.audio_de_clau(parts[1])
                if audio:
                    envia_audio(self, audio)
                else:
                    self.send_error(404)
            else:
                self.send_error(404)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "notes"] and RE_CLAU.match(parts[2]):
            mida = int(self.headers.get("Content-Length") or 0)
            desa_notes(parts[2], json.loads(self.rfile.read(mida) or b"[]"))
            self._json({"ok": True})
        else:
            self.send_error(404)


def clau_de(que: str) -> str:
    """Una clau (banc-100, local-w-…) o el camí d'un analysis.json → la clau. ErrorOrigen si no."""
    clau = origens.normalitza_clau(que)
    return clau if RE_CLAU.match(clau) else origens.registra_fitxer(que)


def inicia(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """El servidor (sense engegar) i la seva URL. L'app l'engega en un fil i hi obre les cançons."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # localhost i no 127.0.0.1: YouTube no deixa reproduir incrustats alguns vídeos des d'una adreça IP
    return srv, f"http://localhost:{srv.server_address[1]}/"


def serveix(port: int = 8766, obre: bool = True, que: str | None = None) -> int:
    """`que`: una clau (banc-100, local-w-…) o el camí d'un analysis.json per obrir de seguida."""
    clau = None
    if que:
        try:
            clau = clau_de(que)
        except origens.ErrorOrigen as e:
            print(e)
            return 1
    srv, base = inicia(port)
    url = base + (f"#id={quote(clau)}&v=temps" if clau else "")
    print(f"Depurador: {url}\n(Ctrl+C per aturar)")
    if obre:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
