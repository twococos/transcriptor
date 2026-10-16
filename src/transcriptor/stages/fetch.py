"""Etapa fetch: URL de YouTube (yt-dlp) o fitxer local → WAV 44,1 kHz estèreo."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..audio import SENSE_FINESTRA, converteix_a_wav, ffmpeg

log = logging.getLogger(__name__)

_RE_YT = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})")


def youtube_id(url: str) -> str | None:
    m = _RE_YT.search(url)
    return m.group(1) if m else None


def es_url(entrada: str) -> bool:
    return entrada.startswith(("http://", "https://"))


def id_canco(entrada: str) -> str:
    """Identificador estable per a la cache: id de YouTube o hash del fitxer."""
    if es_url(entrada):
        yid = youtube_id(entrada)
        if yid:
            return f"yt-{yid}"
        return "url-" + hashlib.sha1(entrada.encode()).hexdigest()[:12]
    h = hashlib.sha1()
    with open(entrada, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return "f-" + h.hexdigest()[:12]


def _entorn_js() -> tuple[list[str], dict]:
    """Arguments i entorn perquè yt-dlp trobi un intèrpret de JS (reptes de YouTube).

    El paquet `deno` de PyPI deixa deno.exe al directori d'scripts de l'entorn, que no sempre és al
    PATH (p. ex. quan l'app s'executa amb pythonw): l'hi afegim.
    """
    scripts = str(Path(sys.executable).parent)
    entorn = {**os.environ, "PATH": scripts + os.pathsep + os.environ.get("PATH", "")}
    if shutil.which("deno", path=entorn["PATH"]):
        return [], entorn
    if shutil.which("node", path=entorn["PATH"]):
        return ["--js-runtimes", "node"], entorn
    log.warning("No hi ha deno ni node: yt-dlp pot fallar amb alguns vídeos de YouTube")
    return [], entorn


# Missatges de yt-dlp que indiquen que el vídeo no es podrà baixar mai (no val la pena reintentar)
ERRORS_PERMANENTS = ("video unavailable", "private video", "has been removed", "copyright",
                     "not available in your country", "confirm your age", "members-only",
                     "is not a valid url", "unsupported url")


class ErrorDescarrega(RuntimeError):
    def __init__(self, missatge: str, permanent: bool):
        super().__init__(missatge)
        self.permanent = permanent


def descarrega(entrada: str, desti: Path) -> dict:
    """Escriu `desti` (WAV) i retorna metadades {title, artist, duration_s, youtube_id, url|fitxer}."""
    if not es_url(entrada):
        converteix_a_wav(Path(entrada), desti)
        return {"fitxer": str(Path(entrada).resolve()), "title": Path(entrada).stem}

    url = entrada
    yid = youtube_id(url)
    if yid:
        url = f"https://www.youtube.com/watch?v={yid}"  # treu llistes i altres paràmetres
    args_js, entorn = _entorn_js()
    with tempfile.TemporaryDirectory(prefix="tx-") as tmp:
        sortida = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-playlist", *args_js,
             "-f", "bestaudio/best", "--ffmpeg-location", ffmpeg(),
             "-o", str(Path(tmp) / "audio.%(ext)s"),
             "--no-simulate", "--print", "%(id)s\t%(title)s\t%(channel)s\t%(duration)s",
             url],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=entorn,
            creationflags=SENSE_FINESTRA,  # els fills (ffmpeg, deno) hereten la consola amagada
        )
        if sortida.returncode != 0:
            error = sortida.stderr.strip()[-500:] or f"yt-dlp ha sortit amb el codi {sortida.returncode}"
            raise ErrorDescarrega(error, permanent=any(e in error.lower() for e in ERRORS_PERMANENTS))
        fitxers = list(Path(tmp).glob("audio.*"))
        if not fitxers:
            raise RuntimeError(f"yt-dlp no ha generat cap fitxer: {sortida.stderr[-500:]}")
        converteix_a_wav(fitxers[0], desti)
    camps = sortida.stdout.strip().splitlines()[-1].split("\t")
    return {"url": url, "youtube_id": camps[0], "title": camps[1], "artist": camps[2]}
