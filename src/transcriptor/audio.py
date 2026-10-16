"""Lectura/escriptura d'àudio i accés a l'ffmpeg portable (imageio-ffmpeg)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr


# Amb pythonw (l'app) no hi ha consola: sense això, cada ffmpeg/yt-dlp n'obriria una de buida un instant
SENSE_FINESTRA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg() -> str:
    """Camí a l'executable ffmpeg que porta la wheel d'imageio-ffmpeg."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def converteix_a_wav(entrada: Path, sortida: Path, sr: int = 44100, canals: int = 2) -> None:
    subprocess.run(
        [ffmpeg(), "-y", "-v", "error", "-i", str(entrada), "-ar", str(sr), "-ac", str(canals),
         "-c:a", "pcm_s16le", str(sortida)],
        check=True, creationflags=SENSE_FINESTRA,
    )


def llegeix(cami: Path, sr: int | None = None, mono: bool = False) -> tuple[np.ndarray, int]:
    """Retorna (senyal float32, sr). Forma: (n,) si mono, (n, canals) si no."""
    senyal, sr_orig = sf.read(str(cami), dtype="float32", always_2d=True)
    if mono:
        senyal = senyal.mean(axis=1)
    if sr and sr != sr_orig:
        senyal = soxr.resample(senyal, sr_orig, sr).astype(np.float32)
        sr_orig = sr
    return senyal, sr_orig


def escriu(cami: Path, senyal: np.ndarray, sr: int) -> None:
    sf.write(str(cami), senyal, sr, subtype="PCM_16", format="WAV")


def durada(cami: Path) -> float:
    info = sf.info(str(cami))
    return info.frames / info.samplerate
