"""Detecció del dispositiu de càlcul i perfil associat.

`detecta("auto")` mira si hi ha CUDA i si funciona de veritat (una operació de prova); si no,
torna a CPU amb un avís. Cap etapa escriu "cuda" a mà: totes reben el `Perfil`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

VRAM_MODELS_GRANS_GB = 6.0


@dataclass(frozen=True)
class Perfil:
    device: str  # "cpu" | "cuda"
    nom: str  # descripció (model de CPU o GPU)
    vram_gb: float
    fils: int
    # Valors per defecte segons el dispositiu (la Config els pot sobreescriure)
    whisper_compute_type: str
    separador: str
    demucs_shifts: int

    def info(self) -> dict:
        return asdict(self)


def _fils_cpu() -> int:
    # Nuclis físics aproximats: amb hyperthreading, torch rendeix millor amb la meitat dels lògics
    logics = os.cpu_count() or 4
    return max(1, logics // 2) if logics >= 4 else logics


def _perfil_cpu(motiu: str | None = None) -> Perfil:
    if motiu:
        log.warning("Es fa servir la CPU: %s", motiu)
    import platform

    return Perfil(device="cpu", nom=platform.processor() or "CPU", vram_gb=0.0, fils=_fils_cpu(),
                  whisper_compute_type="int8", separador="htdemucs", demucs_shifts=0)


def detecta(device: str = "auto") -> Perfil:
    """Retorna el perfil per a `device` ("auto" | "cpu" | "cuda")."""
    if device == "cpu":
        return _perfil_cpu()
    try:
        import torch
    except ImportError:
        return _perfil_cpu("PyTorch no està instal·lat")
    if not torch.cuda.is_available():
        if device == "cuda":
            log.warning("S'ha demanat CUDA però no està disponible")
        return _perfil_cpu("CUDA no disponible" if device == "cuda" else None)
    try:
        # Prova real: drivers antics o GPU no suportades fallen aquí, no a is_available()
        (torch.ones(8, device="cuda") * 2).sum().item()
        props = torch.cuda.get_device_properties(0)
    except Exception as e:  # noqa: BLE001 — qualsevol error de CUDA ens fa tornar a CPU
        return _perfil_cpu(f"CUDA falla ({e})")
    vram = props.total_memory / 1024**3
    grans = vram >= VRAM_MODELS_GRANS_GB
    return Perfil(device="cuda", nom=props.name, vram_gb=round(vram, 1), fils=_fils_cpu(),
                  whisper_compute_type="float16", separador="roformer" if grans else "htdemucs",
                  demucs_shifts=1 if grans else 0)


def configura_fils(perfil: Perfil) -> None:
    try:
        import torch

        torch.set_num_threads(perfil.fils)
    except ImportError:
        pass
