"""Etapa rhythm: pulsacions i inicis de compàs amb Beat This! (sense postprocés DBN/madmom).

El resultat cru es regularitza a postprocess/meter.py (compàs constant per trams).
"""

from __future__ import annotations

import gc
from pathlib import Path

from ..audio import llegeix
from ..device import Perfil


def detecta(mescla: Path, perfil: Perfil) -> dict:
    from beat_this.inference import Audio2Beats

    model = Audio2Beats(checkpoint_path="final0", device=perfil.device, float16=perfil.device == "cuda")
    senyal, sr = llegeix(mescla, mono=True)
    try:
        pulsacions, inicis = model(senyal.astype("float64"), sr)
    finally:
        del model
        gc.collect()
    return {
        "pulsacions": [round(float(t), 3) for t in pulsacions],
        "inicis_compas": [round(float(t), 3) for t in inicis],
    }
