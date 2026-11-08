"""Correcció dels temps de paraula de Whisper a les vores dels trams de veu.

Amb el filtre de veu (VAD), faster-whisper enganxa els trams amb veu traient-ne els silencis i
instrumentals de més de 2 s, transcriu l'àudio enganxat i després torna cada paraula al temps real
segons el tram on cau el seu **punt mig** (`restore_speech_timestamps`). La primera paraula d'una frase
sovint surt allargada cap enrere fins a l'enganxada amb el tram anterior; llavors el punt mig cau dins
el tram anterior i la paraula es retorna just després de la frase anterior, a l'altra banda del silenci
o de l'instrumental ("before [19.98-20.26] Couldn't [20.26-21.50] … look [24.03]").

Senyal: una paraula seguida d'un buit de més d'1 s abans de la següent paraula **del mateix segment**
de Whisper (la frase continua després del buit). Es corregeix si és la primera del segment, o si no
acaba en puntuació: amb puntuació és un final de frase de veritat seguit d'una pausa ("dia, … adeu").
A les 104 cançons de la cache: 165 casos a la primera paraula del segment i 52 dins el segment, gairebé
tots errors; 155 amb puntuació, gairebé tots correctes.

La paraula es mou enganxada a la següent amb una durada normal. Es corregeix com a molt una paraula
per buit: les anteriors cauen senceres dins el tram anterior i el seu temps és bo.
"""

from __future__ import annotations

import re

import numpy as np

MIN_BUIT_S = 1.0
TOL_SEGMENT_S = 0.011  # els temps de Whisper són a 0.01 s
DURADA_DEFECTE_S = 0.3
_RE_PUNTUACIO_FINAL = re.compile(r"[,.;:!?…][\"'»”)\]]*$")


def _segment_de(paraules: list[dict], segments: list[dict]) -> list[int | None]:
    """Índex del segment de cada paraula (None si no cau dins de cap)."""
    sortida: list[int | None] = [None] * len(paraules)
    j = 0
    for k, s in enumerate(segments):
        while j < len(paraules) and paraules[j]["end"] <= s["end"] + TOL_SEGMENT_S:
            if paraules[j]["start"] >= s["start"] - TOL_SEGMENT_S:
                sortida[j] = k
            j += 1
    return sortida


def corregeix(paraules: list[dict], segments: list[dict]) -> dict:
    """Retorna {"paraules", "segments", "correccions": [{text, abans: [s, e], despres: [s, e]}]}."""
    paraules = [dict(p) for p in paraules]
    segments = [dict(s) for s in segments]
    seg = _segment_de(paraules, segments)
    durades = [p["end"] - p["start"] for p in paraules if p["end"] > p["start"]]
    durada_max = 2 * float(np.median(durades)) if durades else DURADA_DEFECTE_S

    correccions = []
    for k in range(len(paraules) - 1):
        p, seguent = paraules[k], paraules[k + 1]
        if seg[k] is None or seg[k] != seg[k + 1] or seguent["start"] - p["end"] <= MIN_BUIT_S:
            continue
        primera = k == 0 or seg[k - 1] != seg[k]
        if not primera and _RE_PUNTUACIO_FINAL.search(p["text"]):
            continue
        abans = [p["start"], p["end"]]
        p["end"] = seguent["start"]
        p["start"] = round(p["end"] - min(abans[1] - abans[0], durada_max), 2)
        if primera:
            segments[seg[k]]["start"] = p["start"]
        correccions.append({"text": p["text"], "abans": abans, "despres": [p["start"], p["end"]]})
    return {"paraules": paraules, "segments": segments, "correccions": correccions}
