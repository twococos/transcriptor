"""Configuració: directoris de treball i paràmetres de cada etapa.

Els valors per defecte surten del perfil del dispositiu (`device.py`); un fitxer YAML
(`configs/*.yaml`) o la CLI poden sobreescriure'ls.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def dir_base() -> Path:
    """Directori de dades (àudio, cache, models). TX_HOME o ./work."""
    return Path(os.environ.get("TX_HOME", "work")).resolve()


class Config(BaseModel):
    # Separació
    # None = valor del perfil del dispositiu (device.py)
    separador: str | None = None  # htdemucs | htdemucs_ft | roformer
    demucs_shifts: int | None = None
    # Acords
    acords_backend: str = "btc"
    acords_vocabulari: str = "sevenths"  # majmin | sevenths | full
    acords_min_pulsacions: float = 1.0  # acords més curts s'eliminen
    # Lletra
    whisper_model: str = "large-v3-turbo"
    whisper_compute_type: str | None = None
    lrclib: bool = True
    afinar_ctc: bool = False  # refinament amb wav2vec2 català (extra `ctc`)
    # Línies i estructura
    pausa_linia_s: float = 0.6
    max_paraules_linia: int = 10
    # Extra lliure per a experiments
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def carrega(cls, fitxer: str | Path | None = None, **sobreescriu) -> "Config":
        dades: dict[str, Any] = {}
        if fitxer:
            dades.update(yaml.safe_load(Path(fitxer).read_text(encoding="utf-8")) or {})
        dades.update({k: v for k, v in sobreescriu.items() if v is not None})
        return cls(**dades)


def prepara_entorn_models() -> Path:
    """Fa que totes les descàrregues de models vagin a <base>/models."""
    models = dir_base() / "models"
    models.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TORCH_HOME", str(models / "torch"))
    os.environ.setdefault("HF_HOME", str(models / "hf"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return models
