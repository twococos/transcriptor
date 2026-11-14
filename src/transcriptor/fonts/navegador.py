"""Navegador sense finestra per a les pàgines amb repte antibots (Ultimate Guitar i E-Chords amb
Cloudflare, Cifra Club amb Akamai).

Sense dependències noves: s'engega l'Edge o el Chrome del sistema (Edge és a tots els Windows i
està signat, així no topa amb Smart App Control) amb el port de DevTools i es controla pel
protocol CDP amb `websockets`. A Linux/Docker, `chromium`. Si no n'hi ha cap, `disponible()` és
False i el lloc que el necessita se salta. El navegador es presenta amb el seu User-Agent sense
"Headless" (Akamai rebutja "HeadlessChrome").
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from websockets.sync.client import connect

log = logging.getLogger(__name__)

CANDIDATS_WINDOWS = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
]
CANDIDATS_LINUX = ["chromium", "chromium-browser", "google-chrome", "microsoft-edge"]
INTERVAL_S = 2.0  # entre dues pàgines del mateix domini (els dominis diferents van en paral·lel)


def executable() -> str | None:
    if os.environ.get("TX_NAVEGADOR"):
        return os.environ["TX_NAVEGADOR"]
    if os.name == "nt":
        for c in CANDIDATS_WINDOWS:
            p = os.path.expandvars(c)
            if os.path.exists(p):
                return p
        return None
    return next((shutil.which(c) for c in CANDIDATS_LINUX if shutil.which(c)), None)


def disponible() -> bool:
    return executable() is not None


class Navegador:
    """`with Navegador() as nav: nav.avalua(url, expressio_js)`. Un procés per a tota la cerca."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.dir: Path | None = None
        self.port = 0
        self.ua: str | None = None
        self._ultima: dict[str, float] = {}
        self._bloquejos: dict[str, threading.Lock] = {}
        self._bloqueig = threading.Lock()

    def __enter__(self) -> "Navegador":
        exe = executable()
        if exe is None:
            raise RuntimeError("No hi ha cap navegador Chromium al sistema")
        self._engega(exe)
        # L'User-Agent sense "Headless" s'ha de passar en engegar (canviar-lo per pestanya fa que el
        # repte de Cloudflare no passi): primer s'engega per saber la versió i després es torna a engegar.
        ua = self._agent()
        if ua and "HeadlessChrome" in ua:
            self.__exit__()
            self.ua = ua.replace("HeadlessChrome", "Chrome")
            self._engega(exe, [f"--user-agent={self.ua}"])
        return self

    def _engega(self, exe: str, extra: list[str] | None = None) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="tx-nav-"))
        args = [exe, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.dir}",
                "--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check",
                "--window-size=1280,900", "--mute-audio", "--remote-allow-origins=*"] + (extra or [])
        if os.name != "nt" and os.geteuid() == 0:
            args.append("--no-sandbox")  # Docker com a root
        self.proc = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        f = self.dir / "DevToolsActivePort"
        for _ in range(200):
            if f.exists() and f.read_text().strip():
                self.port = int(f.read_text().splitlines()[0])
                return
            time.sleep(0.1)
        self.__exit__()
        raise RuntimeError("El navegador no ha obert el port de DevTools")

    def __exit__(self, *_) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir = None

    def _agent(self) -> str | None:
        try:
            return requests.get(f"http://127.0.0.1:{self.port}/json/version", timeout=10).json()["User-Agent"]
        except Exception:  # noqa: BLE001
            return None

    def avalua(self, url: str, expressio: str, limit_s: float = 30) -> object | None:
        """Obre `url` en una pestanya nova i retorna el primer valor no buit de l'expressió JS
        (s'avalua cada mig segon fins a `limit_s`). None si no n'hi ha o si hi ha cap error."""
        domini = (urlparse(url).hostname or "").removeprefix("www.")
        with self._bloqueig:
            bloqueig = self._bloquejos.setdefault(domini, threading.Lock())
        with bloqueig:
            espera = self._ultima.get(domini, 0.0) + INTERVAL_S - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            try:
                return self._avalua(url, expressio, limit_s)
            except Exception as e:  # noqa: BLE001 — una pàgina que falla no ha d'aturar la cerca
                log.info("Navegador: %s (%s)", url, e)
                return None
            finally:
                self._ultima[domini] = time.monotonic()

    def _avalua(self, url: str, expressio: str, limit_s: float) -> object | None:
        base = f"http://127.0.0.1:{self.port}"
        pestanya = requests.put(f"{base}/json/new?about:blank", timeout=10).json()
        try:
            with connect(pestanya["webSocketDebuggerUrl"], max_size=None, open_timeout=10) as ws:
                n = 0

                def crida(metode: str, **params):
                    nonlocal n
                    n += 1
                    ws.send(json.dumps({"id": n, "method": metode, "params": params}))
                    while True:
                        m = json.loads(ws.recv(timeout=30))
                        if m.get("id") == n:
                            return m.get("result", {})

                crida("Page.enable")
                crida("Page.addScriptToEvaluateOnNewDocument",
                      source="Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                crida("Page.navigate", url=url)
                fi = time.monotonic() + limit_s
                while time.monotonic() < fi:
                    time.sleep(0.5)
                    r = crida("Runtime.evaluate", expression=expressio, returnByValue=True)
                    valor = r.get("result", {}).get("value")
                    if valor:
                        return valor
                log.info("Navegador: %s sense resultat en %.0f s", url, limit_s)
                return None
        finally:
            requests.get(f"{base}/json/close/{pestanya['id']}", timeout=10)
