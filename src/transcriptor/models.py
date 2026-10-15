"""Descàrrega anticipada dels models (primer arrencament de l'app o `tx models`).

Fase 0: a connexions lentes, els models triguen molt a baixar (Whisper turbo 1,6 GB). Millor fer-ho
un cop, amb progrés visible, que no pas a mitja feina amb un lease corrent.
"""

from __future__ import annotations

import logging
from typing import Callable

from .config import Config, prepara_entorn_models
from .device import Perfil

log = logging.getLogger(__name__)

Progres = Callable[[str, int, int], None]  # (missatge, pas, total)


def prepara(perfil: Perfil, cfg: Config | None = None, progres: Progres | None = None) -> None:
    cfg = cfg or Config()
    progres = progres or (lambda m, i, n: log.info("[%d/%d] %s", i, n, m))
    dir_models = prepara_entorn_models()
    separador = cfg.separador or perfil.separador
    passos: list[tuple[str, Callable[[], None]]] = []

    def demucs() -> None:
        from demucs.pretrained import get_model

        get_model("htdemucs")

    def roformer() -> None:
        from audio_separator.separator import Separator

        from .stages.separate import MODEL_ROFORMER

        sep = Separator(model_file_dir=str(dir_models / "audiosep"))
        sep.download_model_files(MODEL_ROFORMER)

    def beat_this() -> None:
        from beat_this.inference import load_checkpoint

        load_checkpoint("final0", device="cpu")

    def btc() -> None:
        from .stages.chords import _pesos

        _pesos(dir_models)

    def whisper() -> None:
        from faster_whisper.utils import download_model

        download_model(cfg.whisper_model)

    passos.append(("Model de separació (htdemucs, 80 MB)", demucs))
    if separador == "roformer":
        passos.append(("Model de separació Mel-RoFormer (900 MB)", roformer))
    passos += [
        ("Model de ritme (Beat This!, 80 MB)", beat_this),
        ("Model d'acords (BTC, 12 MB)", btc),
        (f"Model de lletra (Whisper {cfg.whisper_model}, 1,6 GB)", whisper),
    ]
    for i, (missatge, funcio) in enumerate(passos, 1):
        progres(missatge, i, len(passos))
        funcio()
    progres("Models a punt", len(passos), len(passos))
