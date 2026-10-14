"""Etapa chords: probabilitats d'acord per trama amb BTC (vocabulari gran, 170 classes).

Desa la matriu de probabilitats (trames × 170) perquè el postprocés pugui decidir l'acord de cada
pulsació sumant-hi les probabilitats, en lloc de partir de segments ja retallats.
"""

from __future__ import annotations

import gc
import logging
import urllib.request
from pathlib import Path

import numpy as np

from ..audio import llegeix
from ..device import Perfil
from ..vendor.btc import CONFIG_AUDIO, CONFIG_MODEL, BTC_model, idx_a_acord

log = logging.getLogger(__name__)

URL_PESOS = "https://github.com/jayg996/BTC-ISMIR19/raw/master/test/btc_model_large_voca.pt"


def _pesos(dir_models: Path) -> Path:
    f = dir_models / "btc" / "btc_model_large_voca.pt"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        log.info("Descarregant els pesos de BTC (12 MB)...")
        tmp = f.with_suffix(".part")
        urllib.request.urlretrieve(URL_PESOS, tmp)
        tmp.replace(f)
    return f


def _cqt(senyal: np.ndarray, sr: int) -> np.ndarray:
    """CQT logarítmica per blocs de 10 s, com l'original (per fidelitat amb l'entrenament)."""
    import librosa

    c = CONFIG_AUDIO
    bloc = int(sr * c["inst_len"])
    parts = []
    for i in range(0, len(senyal), bloc):
        tros = senyal[i : i + bloc]
        if len(tros) < c["hop_length"]:
            break
        parts.append(librosa.cqt(tros, sr=sr, n_bins=c["n_bins"], bins_per_octave=c["bins_per_octave"],
                                 hop_length=c["hop_length"]))
    return np.log(np.abs(np.concatenate(parts, axis=1)) + 1e-6)


def probabilitats(mescla: Path, perfil: Perfil, dir_models: Path) -> tuple[np.ndarray, float]:
    """Retorna (probabilitats [trames, 170], segons per trama)."""
    import torch

    punt = torch.load(_pesos(dir_models), map_location="cpu", weights_only=False)
    model = BTC_model(CONFIG_MODEL).to(perfil.device).eval()
    model.load_state_dict(punt["model"])

    senyal, sr = llegeix(mescla, sr=CONFIG_AUDIO["song_hz"], mono=True)
    caract = (_cqt(senyal, sr).T - punt["mean"]) / punt["std"]
    per_trama = CONFIG_AUDIO["inst_len"] / CONFIG_MODEL["timestep"]

    n = CONFIG_MODEL["timestep"]
    reals = caract.shape[0]
    caract = np.pad(caract, ((0, (-reals) % n), (0, 0)))
    x = torch.tensor(caract, dtype=torch.float32, device=perfil.device).view(-1, n, caract.shape[1])
    with torch.no_grad():
        probs = model(x).reshape(-1, CONFIG_MODEL["num_chords"])[:reals].cpu().numpy()
    del model
    gc.collect()
    return probs.astype(np.float32), per_trama


def segments(probs: np.ndarray, per_trama: float) -> list[dict]:
    """Segments crus (trames consecutives amb la mateixa classe), per a inspecció i proves."""
    idx = probs.argmax(axis=1)
    sortida, inici = [], 0
    for k in range(1, len(idx) + 1):
        if k == len(idx) or idx[k] != idx[inici]:
            sortida.append({"start": round(inici * per_trama, 3), "end": round(k * per_trama, 3),
                            "raw": idx_a_acord(int(idx[inici])),
                            "conf": round(float(probs[inici:k, idx[inici]].mean()), 3)})
            inici = k
    return sortida
