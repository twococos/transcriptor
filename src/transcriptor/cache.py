"""Cache per etapa a <base>/cache/<id>/.

Cada etapa desa el seu resultat (JSON o WAV) i un fitxer `<etapa>.params.json` amb els paràmetres
que l'han produït. Si els paràmetres canvien, l'etapa es torna a calcular. Així es pot iterar la
fusió i el render sense refer minuts de separació i transcripció.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from .config import dir_base

log = logging.getLogger(__name__)


class Cache:
    def __init__(self, id_canco: str, base: Path | None = None):
        self.dir = (base or dir_base() / "cache") / id_canco
        self.dir.mkdir(parents=True, exist_ok=True)
        self.temps: dict[str, float] = {}

    def cami(self, nom: str) -> Path:
        return self.dir / nom

    def _params_ok(self, etapa: str, params: dict) -> bool:
        f = self.cami(f"{etapa}.params.json")
        return f.exists() and json.loads(f.read_text(encoding="utf-8")) == params

    def _desa_params(self, etapa: str, params: dict) -> None:
        self.cami(f"{etapa}.params.json").write_text(json.dumps(params, sort_keys=True), encoding="utf-8")

    def json(self, etapa: str, params: dict, calcula: Callable[[], Any]) -> Any:
        """Resultat JSON de l'etapa, de la cache si els paràmetres coincideixen."""
        f = self.cami(f"{etapa}.json")
        if f.exists() and self._params_ok(etapa, params):
            log.info("%s: de la cache", etapa)
            return json.loads(f.read_text(encoding="utf-8"))
        inici = time.perf_counter()
        resultat = calcula()
        self.temps[etapa] = round(time.perf_counter() - inici, 1)
        log.info("%s: %.1f s", etapa, self.temps[etapa])
        f.write_text(json.dumps(resultat, ensure_ascii=False), encoding="utf-8")
        self._desa_params(etapa, params)
        return resultat

    def fitxer(self, etapa: str, nom: str, params: dict, calcula: Callable[[Path], None]) -> Path:
        """Resultat en forma de fitxer (p. ex. WAV); `calcula(destí)` l'ha d'escriure."""
        f = self.cami(nom)
        if f.exists() and self._params_ok(etapa, params):
            log.info("%s: de la cache", etapa)
            return f
        inici = time.perf_counter()
        temporal = f.with_suffix(".tmp" + f.suffix)
        calcula(temporal)
        temporal.replace(f)
        self.temps[etapa] = round(time.perf_counter() - inici, 1)
        log.info("%s: %.1f s", etapa, self.temps[etapa])
        self._desa_params(etapa, params)
        return f

    def esborra_audio(self) -> None:
        """Esborra l'àudio (no s'emmagatzema àudio de YouTube); conserva els JSON."""
        for f in self.dir.glob("*.wav"):
            f.unlink(missing_ok=True)
