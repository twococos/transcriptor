"""Descàrrega anticipada dels models (primer arrencament de l'app o `tx models`).

Fase 0: a connexions lentes, els models triguen molt a baixar (Whisper turbo 1,6 GB). Millor fer-ho
un cop, amb progrés visible, que no pas a mitja feina amb un lease corrent.

El progrés es compta amb els bytes rebuts, no pas mirant com creix el directori: Hugging Face (xet)
escriu el fitxer sencer al final de la descàrrega.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Config, prepara_entorn_models
from .device import Perfil

log = logging.getLogger(__name__)

Progres = Callable[[str, int, int], None]  # (missatge, pas, total)


@dataclass
class EstatDescarrega:
    """Progrés en bytes, per a la barra de l'app. Cada pas compta la seva mida esperada quan acaba
    (encara que ja hi fos); durant el pas, els bytes rebuts."""
    total: int = 0
    fet: int = 0  # bytes dels passos acabats
    rebut_pas: int = 0
    mida_pas: int = 0
    pas: str = ""
    i: int = 0
    n: int = 0
    acabat: bool = False

    def bytes(self) -> int:
        if self.acabat:
            return self.total
        return min(self.fet + min(self.rebut_pas, self.mida_pas), self.total)


def _classe_tqdm(estat: EstatDescarrega):
    """Barra tqdm muda que suma els bytes descarregats a `estat` (per a Hugging Face i torch.hub)."""
    from tqdm.auto import tqdm

    class Comptador(tqdm):
        def __init__(self, *args, **kwargs):
            # Hugging Face (xet) fa dues barres en bytes: la de baixar i la de reconstruir el fitxer
            self._compta = kwargs.get("unit") == "B" and not str(kwargs.get("desc") or "").startswith("Reconstruct")
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            if self._compta and n:
                estat.rebut_pas += n
            return super().update(n)

    return Comptador


@contextlib.contextmanager
def _torch_hub_amb(classe):
    import torch.hub

    original = torch.hub.tqdm
    torch.hub.tqdm = classe
    try:
        yield
    finally:
        torch.hub.tqdm = original


def prepara(perfil: Perfil, cfg: Config | None = None, progres: Progres | None = None,
            estat: EstatDescarrega | None = None) -> None:
    cfg = cfg or Config()
    progres = progres or (lambda m, i, n: log.info("[%d/%d] %s", i, n, m))
    dir_models = prepara_entorn_models()
    separador = cfg.separador or perfil.separador
    estat = estat or EstatDescarrega()
    comptador = _classe_tqdm(estat)
    passos: list[tuple[str, int, Callable[[], None]]] = []

    def demucs() -> None:
        import yaml
        from demucs.hf import DEFAULT_NAMESPACE, hf_repo_name
        from demucs.pretrained import get_model
        from huggingface_hub import hf_hub_download

        # Els mateixos fitxers que baixa demucs (demucs/hf.py), però amb el comptador de bytes
        try:
            repo = f"{DEFAULT_NAMESPACE}/{hf_repo_name('htdemucs')}"
            bossa = yaml.safe_load(Path(hf_hub_download(repo, "htdemucs.yaml", tqdm_class=comptador))
                                   .read_text(encoding="utf-8"))
            for sig in bossa["models"]:
                hf_hub_download(repo, f"{sig}.safetensors", tqdm_class=comptador)
        except Exception:  # noqa: BLE001 — get_model ho torna a provar (i té el repositori antic de reserva)
            log.warning("No s'ha pogut baixar htdemucs de Hugging Face", exc_info=True)
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
        import huggingface_hub
        from faster_whisper.utils import _MODELS, download_model

        repo = _MODELS.get(cfg.whisper_model)
        if repo is None:
            download_model(cfg.whisper_model)
            return
        # Com download_model (faster_whisper/utils.py), però amb el comptador de bytes
        huggingface_hub.snapshot_download(repo, tqdm_class=comptador, allow_patterns=[
            "config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"])

    passos.append(("Model de separació (htdemucs, 80 MB)", 84_025_501, demucs))
    if separador == "roformer":
        passos.append(("Model de separació Mel-RoFormer (900 MB)", 913_136_111, roformer))
    passos += [
        ("Model de ritme (Beat This!, 80 MB)", 81_058_141, beat_this),
        ("Model d'acords (BTC, 12 MB)", 12_229_576, btc),
        (f"Model de lletra (Whisper {cfg.whisper_model}, 1,6 GB)", 1_621_667_008, whisper),
    ]
    estat.total, estat.n = sum(m for _, m, _ in passos), len(passos)
    with _torch_hub_amb(comptador):
        for i, (missatge, mida, funcio) in enumerate(passos, 1):
            estat.pas, estat.i, estat.mida_pas, estat.rebut_pas = missatge, i, mida, 0
            progres(missatge, i, len(passos))
            funcio()
            estat.fet += mida
    estat.acabat = True
    progres("Models a punt", len(passos), len(passos))
