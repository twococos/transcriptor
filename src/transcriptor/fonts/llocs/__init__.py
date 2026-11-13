"""Un mòdul per lloc. Cadascun exposa:

- `LLOC`: nom curt ("ultimate_guitar", "cifraclub"...).
- `cerca(titol, artista, idioma) -> list[Candidat]`: les versions que semblen la cançó, millors primer.
- `baixa(candidat) -> TabCrua | None`.
- `parseja(html, url) -> TabCrua | None`: sense xarxa (per als tests amb tests/fixtures/fonts/).

Cap funció llança excepcions: una font que falla o ha canviat de format s'ignora (amb un log).
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

LLINDAR_TITOL = 0.8
LLINDAR_ARTISTA = 0.6


def pla(text: str) -> str:
    """Minúscules, sense accents ni puntuació, espais simples."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)  # "(versión acústica)", "[Live]"
    return " ".join(re.findall(r"[a-z0-9]+", text))


def slug(text: str, sep: str = "-") -> str:
    return pla(text).replace(" ", sep)


def _sim(a: str, b: str) -> float:
    a, b = pla(a), pla(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # "The Beatles" / "Beatles", "Sau" / "Sau i Carles Sabater"
    if a.removeprefix("the ") == b.removeprefix("the ") or (len(a) >= 3 and (b.startswith(a + " ") or a.startswith(b + " "))):
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def puntuacio(titol: str, artista: str, c_titol: str, c_artista: str) -> float:
    """Per ordenar candidats: similitud del títol + 0,5 · la de l'artista."""
    return _sim(titol, c_titol) + 0.5 * (_sim(artista, c_artista) if artista else 1.0)


def acceptable(titol: str, artista: str, c_titol: str, c_artista: str) -> bool:
    if _sim(titol, c_titol) < LLINDAR_TITOL:
        return False
    return not artista or not c_artista or _sim(artista, c_artista) >= LLINDAR_ARTISTA
