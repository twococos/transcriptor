"""Utilitats de text compartides per les proves de lletra."""

import re
import unicodedata


def normalitza(text: str) -> list[str]:
    """Paraules en minúscula, sense puntuació (conserva accents i l·l)."""
    text = unicodedata.normalize("NFC", text.lower()).replace("’", "'")
    text = text.replace("l.l", "l·l")
    return re.findall(r"[\w·]+", text)


def wer(referencia: list[str], hipotesi: list[str]) -> float:
    """Word error rate per distància d'edició (Levenshtein) a nivell de paraula."""
    anterior = list(range(len(hipotesi) + 1))
    for i, r in enumerate(referencia, 1):
        actual = [i] + [0] * len(hipotesi)
        for j, h in enumerate(hipotesi, 1):
            actual[j] = min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (r != h))
        anterior = actual
    return anterior[-1] / max(len(referencia), 1)
