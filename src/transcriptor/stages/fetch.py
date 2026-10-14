"""Etapa fetch: URL de YouTube (yt-dlp) o fitxer local → WAV 44,1 kHz estèreo."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ..audio import converteix_a_wav, ffmpeg

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


def _args_js_runtime() -> list[str]:
    # yt-dlp necessita un intèrpret de JS per als reptes de YouTube; per defecte busca deno
    if shutil.which("deno"):
        return []
    if shutil.which("node"):
        return ["--js-runtimes", "node"]
    log.warning("No hi ha deno ni node: yt-dlp pot fallar amb alguns vídeos de YouTube")
    return []


def descarrega(entrada: str, desti: Path) -> dict:
    """Escriu `desti` (WAV) i retorna metadades {title, artist, duration_s, youtube_id, url|fitxer}."""
    if not es_url(entrada):
        converteix_a_wav(Path(entrada), desti)
        return {"fitxer": str(Path(entrada).resolve()), "title": Path(entrada).stem}

    url = entrada
    yid = youtube_id(url)
    if yid:
        url = f"https://www.youtube.com/watch?v={yid}"  # treu llistes i altres paràmetres
    with tempfile.TemporaryDirectory(prefix="tx-") as tmp:
        sortida = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-playlist", *_args_js_runtime(),
             "-f", "bestaudio/best", "--ffmpeg-location", ffmpeg(),
             "-o", str(Path(tmp) / "audio.%(ext)s"),
             "--no-simulate", "--print", "%(id)s\t%(title)s\t%(channel)s\t%(duration)s",
             url],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        fitxers = list(Path(tmp).glob("audio.*"))
        if not fitxers:
            raise RuntimeError(f"yt-dlp no ha generat cap fitxer: {sortida.stderr[-500:]}")
        converteix_a_wav(fitxers[0], desti)
    camps = sortida.stdout.strip().splitlines()[-1].split("\t")
    return {"url": url, "youtube_id": camps[0], "title": camps[1], "artist": camps[2]}
