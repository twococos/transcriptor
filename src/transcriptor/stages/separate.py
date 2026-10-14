"""Etapa separate: extreu la pista de veu (htdemucs, htdemucs_ft o Mel-RoFormer)."""

from __future__ import annotations

import gc
import logging
import tempfile
from pathlib import Path

import numpy as np

from ..audio import escriu, llegeix
from ..device import Perfil

log = logging.getLogger(__name__)

MODEL_ROFORMER = "vocals_mel_band_roformer.ckpt"


def separa_veu(mescla: Path, desti: Path, perfil: Perfil, model: str, shifts: int, dir_models: Path) -> str:
    """Escriu la veu a `desti` (WAV). Retorna el nom del model usat."""
    if model == "roformer":
        try:
            return _roformer(mescla, desti, perfil, dir_models)
        except ImportError:
            log.warning("audio-separator no està instal·lat (extra `roformer`): es fa servir htdemucs")
            model = "htdemucs"
    return _demucs(mescla, desti, perfil, model, shifts)


def _demucs(mescla: Path, desti: Path, perfil: Perfil, model: str, shifts: int) -> str:
    import torch
    from demucs.api import Separator

    sep = Separator(model=model, device=perfil.device, shifts=shifts, progress=False)
    senyal, sr = llegeix(mescla)
    try:
        _, fonts = sep.separate_tensor(torch.from_numpy(np.ascontiguousarray(senyal.T)), sr)
    finally:
        del sep
        gc.collect()
        if perfil.device == "cuda":
            torch.cuda.empty_cache()
    escriu(desti, fonts["vocals"].numpy().T, 44100)
    return model


def _roformer(mescla: Path, desti: Path, perfil: Perfil, dir_models: Path) -> str:
    from audio_separator.separator import Separator

    with tempfile.TemporaryDirectory(prefix="tx-sep-") as tmp:
        sep = Separator(model_file_dir=str(dir_models / "audiosep"), output_dir=tmp, output_format="WAV",
                        output_single_stem="Vocals")
        sep.load_model(model_filename=MODEL_ROFORMER)
        fitxers = sep.separate(str(mescla))
        veu = Path(tmp) / Path(fitxers[0]).name
        senyal, sr = llegeix(veu)
        escriu(desti, senyal, sr)
        del sep
        gc.collect()
    return "mel_roformer"
