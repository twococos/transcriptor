"""Traça del postprocés: què ha sortit de cada pas, per al depurador (`tx depura`, depura/).

`pipeline.executa` i algunes etapes accepten `traca`: si és None no fan res de més. Cada pas desa una
còpia (en tipus JSON) de les seves dades, així els passos següents no la poden modificar.
"""

from __future__ import annotations

import numpy as np


def net(x):
    """Còpia en tipus JSON: numpy a llistes, tuples a llistes, reals amb 3 decimals (ms i probabilitats)."""
    if isinstance(x, dict):
        return {str(k): net(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [net(v) for v in x]
    if isinstance(x, np.ndarray):
        return net(x.tolist())
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return round(v, 3) if np.isfinite(v) else None
    return x


class Traca:
    def __init__(self) -> None:
        self.passos: dict[str, dict] = {}

    def pas(self, nom: str, **dades) -> None:
        self.passos[nom] = net(dades)

    def a_dict(self) -> dict:
        return self.passos


def top(p: np.ndarray, n: int = 6) -> list[list[list]]:
    """Per a cada fila de `p` (unitats × etiquetes), les n columnes més altes: [[índex, valor], ...]."""
    idx = np.argsort(-p, axis=1)[:, :n]
    return [[[int(k), round(float(fila[k]), 3)] for k in ks] for fila, ks in zip(p, idx)]
