"""Cançons fetes pel worker de l'app, desades al disc per poder-les obrir al visor.

<base>/fetes/<id de la feina>/:
- `analysis.json`: l'anàlisi completa (SongAnalysis), la que llegeix el visor.
- `info.json`: títol, artista, data i durada del càlcul.
- `audio.opus` (opcional, ~3 MB): l'àudio comprimit. Sense, el visor fa servir el vídeo de YouTube.

Només és local: no s'envia enlloc i l'usuari ho pot esborrar des de l'app.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import ffmpeg
from .config import dir_base

log = logging.getLogger(__name__)


def dir_fetes() -> Path:
    return dir_base() / "fetes"


@dataclass
class Feta:
    dir: Path
    titol: str
    artista: str
    data: float  # epoch
    segons: int
    te_audio: bool
    mida: int  # bytes al disc

    @property
    def nom(self) -> str:
        return " — ".join(p for p in (self.titol, self.artista) if p) or self.dir.name


def desa(id_feina: int, feina: dict, analisi_json: str, wav: Path | None, segons: float,
         amb_audio: bool = True) -> Path:
    desti = dir_fetes() / str(id_feina)
    desti.mkdir(parents=True, exist_ok=True)
    (desti / "analysis.json").write_text(analisi_json, encoding="utf-8")
    if amb_audio and wav and wav.is_file():
        temporal = desti / "audio.tmp.opus"
        try:
            subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "96k",
                            str(temporal)], check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            temporal.replace(desti / "audio.opus")
        except (OSError, subprocess.CalledProcessError) as e:
            log.warning("No s'ha pogut desar l'àudio de la feina %s: %s", id_feina, e)
            temporal.unlink(missing_ok=True)
    info = {"titol": feina.get("title") or "", "artista": feina.get("artist") or "",
            "font": feina.get("source_url"), "data": time.time(), "segons": round(segons)}
    (desti / "info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return desti


def llista() -> list[Feta]:
    """Les cançons desades, de la més recent a la més antiga."""
    fetes = []
    if not dir_fetes().is_dir():
        return fetes
    for d in dir_fetes().iterdir():
        try:
            info = json.loads((d / "info.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (d / "analysis.json").is_file():
            continue
        fetes.append(Feta(dir=d, titol=info.get("titol", ""), artista=info.get("artista", ""),
                          data=info.get("data", 0), segons=info.get("segons", 0),
                          te_audio=(d / "audio.opus").is_file(),
                          mida=sum(f.stat().st_size for f in d.iterdir() if f.is_file())))
    # A igual data (resolució del rellotge), l'id de feina més alt és la més nova
    return sorted(fetes, key=lambda f: (f.data, int(f.dir.name) if f.dir.name.isdigit() else 0), reverse=True)


def esborra(feta: Feta) -> None:
    shutil.rmtree(feta.dir, ignore_errors=True)


def esborra_totes() -> None:
    shutil.rmtree(dir_fetes(), ignore_errors=True)
