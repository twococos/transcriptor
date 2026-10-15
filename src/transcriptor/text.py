"""Utilitats de text: normalització i tokenització de lletres."""

from __future__ import annotations

import re
import unicodedata

_RE_SUBPARAULA = re.compile(r"[\w·]+")


def normalitza(text: str) -> list[str]:
    """Subparaules en minúscula sense puntuació. "L'avi" → ["l", "avi"]; conserva accents i l·l."""
    text = unicodedata.normalize("NFC", text.lower()).replace("’", "'").replace("l.l", "l·l")
    return _RE_SUBPARAULA.findall(text)


def lletres(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalpha())


def linies_de_text(text: str) -> list[list[str]]:
    """Text de lletra → línies de paraules visibles (tal com s'han d'escriure). Salta línies buides."""
    sortida = []
    for linia in text.replace("\r", "").split("\n"):
        paraules = linia.split()
        if paraules and lletres(linia):
            sortida.append(paraules)
    return sortida


def wer(referencia: list[str], hipotesi: list[str]) -> float:
    """Word error rate per distància d'edició a nivell de paraula."""
    anterior = list(range(len(hipotesi) + 1))
    for i, r in enumerate(referencia, 1):
        actual = [i] + [0] * len(hipotesi)
        for j, h in enumerate(hipotesi, 1):
            actual[j] = min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (r != h))
        anterior = actual
    return anterior[-1] / max(len(referencia), 1)


# Paraules funcionals pròpies de cada idioma (exclusives entre si) per detectar l'idioma d'una lletra
_PARAULES_IDIOMA = {
    "ca": {"els", "amb", "és", "i", "dels", "em", "et", "ens", "jo", "som", "quan", "tot", "mai", "molt",
           "perquè", "també", "aquest", "ara", "teu", "nit", "sóc", "vull", "avui", "res", "ningú", "allà",
           "ets", "hi", "ho", "ja", "més", "pel", "sense", "mentre", "però", "fins", "seu", "aquí", "cap"},
    "es": {"los", "y", "con", "por", "nos", "yo", "somos", "cuando", "todo", "nunca", "muy", "porque",
           "también", "este", "ahora", "noche", "soy", "quiero", "hoy", "nada", "nadie", "allí", "eres",
           "ya", "más", "pero", "sin", "mientras", "hasta", "estoy", "contigo", "corazón"},
    "en": {"the", "and", "you", "to", "of", "is", "it", "my", "we", "your", "on", "be", "are", "love",
           "all", "what", "so", "don't", "can", "will", "just", "i'm", "it's", "with", "this"},
    "fr": {"le", "et", "je", "nous", "vous", "est", "pas", "avec", "pour", "dans", "une", "qui", "mon",
           "ton", "c'est", "moi", "toi", "suis"},
    "pt": {"não", "você", "eu", "uma", "do", "da", "em", "mas", "pra", "meu", "minha", "tudo", "sou"},
}


def detecta_idioma(text: str) -> str | None:
    """Idioma d'una lletra per paraules funcionals ("ca", "es", "en", "fr", "pt"), o None si no és clar."""
    paraules = re.findall(r"[\w'’·]+", unicodedata.normalize("NFC", text.lower()).replace("’", "'"))
    if len(paraules) < 15:
        return None
    punts = {idioma: sum(p in conj for p in paraules) for idioma, conj in _PARAULES_IDIOMA.items()}
    millor = max(punts, key=punts.get)
    segon = sorted(punts.values())[-2]
    return millor if punts[millor] >= 5 and punts[millor] >= 1.5 * segon else None
