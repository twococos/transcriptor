"""Configuració de l'app d'escriptori (%APPDATA%\\Transcriptor\\config.json)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .windows import desprotegeix, protegeix

API_PER_DEFECTE = "https://guitarreo.cat"


def dir_app() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "Transcriptor"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Preferencies:
    api: str = API_PER_DEFECTE
    token_protegit: str = ""  # DPAPI; mai en clar al disc
    nom_worker: str = ""
    actiu: bool = False  # el worker s'engega en obrir l'app
    nomes_inactiu: bool = True
    minuts_inactiu: int = 5
    max_fils: int = 0  # 0 = automàtic
    dispositiu: str = "auto"
    arrencar_amb_windows: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def token(self) -> str:
        try:
            return desprotegeix(self.token_protegit)
        except OSError:
            return ""

    @token.setter
    def token(self, valor: str) -> None:
        self.token_protegit = protegeix(valor.strip()) if valor.strip() else ""

    @classmethod
    def carrega(cls, fitxer: Path | None = None) -> "Preferencies":
        f = fitxer or dir_app() / "config.json"
        if not f.exists():
            return cls()
        dades = json.loads(f.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in dades.items() if k in cls.__dataclass_fields__})

    def desa(self, fitxer: Path | None = None) -> None:
        f = fitxer or dir_app() / "config.json"
        f.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
