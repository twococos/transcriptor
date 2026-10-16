"""Estadístiques d'una feina: com s'ha fet la transcripció (no què hi ha a l'àudio, que és l'anàlisi).

Temps per etapa, dispositiu, d'on surt la lletra i confiances. Viatgen al canconer com a JSON obert
(`stats` del resultat, vegeu docs/api_worker.md) i es desen en local amb cada cançó feta. Es poden
afegir camps nous sense tocar el servidor: només en valida `v`, `audio.duration_s` i `timing`.

Confiances:
- `lyrics.matched_ratio`: part del text conegut (BD, LRCLIB o enganxat) que l'alineació ha pogut
  aparellar amb una paraula sentida per Whisper. La resta de temps s'interpolen.
- `lyrics.timed_ratio`: part de les paraules finals amb temps propi (no interpolat).
- `lyrics.asr_mean_conf`: probabilitat mitjana que Whisper dona a cada paraula que ha sentit.
- `chords.mean_conf`: probabilitat mitjana del camí de Viterbi dels acords (BTC), ponderada per durada.
- `key.confidence`: puntuació del to (perfils de Krumhansl).
"""

from __future__ import annotations

from . import __version__
from .device import Perfil
from .schema import SongAnalysis

VERSIO = 1

# Noms de les etapes de la cache (claus de `timing.stages_s`), per a l'app
NOMS_ETAPES = {
    "fetch": "Baixar l'àudio",
    "separate": "Separar la veu",
    "rhythm": "Ritme i compàs",
    "chords": "Acords",
    "lyrics_source": "Buscar la lletra",
    "lyrics_asr": "Desxifrar la lletra",
    "lyrics_ctc": "Afinar la lletra",
    "postproces": "Muntar la cançó",
}


def _mitjana(valors: list[float], pesos: list[float] | None = None) -> float | None:
    if not valors:
        return None
    pesos = pesos or [1.0] * len(valors)
    total = sum(pesos)
    if total <= 0:
        return round(sum(valors) / len(valors), 3)
    return round(sum(v * p for v, p in zip(valors, pesos)) / total, 3)


def calcula(analisi: SongAnalysis, perfil: Perfil, cached: set[str], alineacio: dict | None,
            confs_asr: list[float], vocabulari: str) -> dict:
    """Objecte `stats` (v1) sense els camps que només sap el worker (`app_version`, `timing.wall_s`).

    `alineacio`: el resultat de `lyrics_align.alinea` (None si la lletra ve de Whisper).
    `confs_asr`: la probabilitat de Whisper de cada paraula sentida."""
    temps = dict(analisi.temps_etapes_s)
    total = temps.pop("total", None)
    paraules = analisi.words

    lletra: dict = {
        "source": analisi.lyrics_source,
        "align": analisi.models.get("lyrics_align", "cap"),
        "asr_mean_conf": _mitjana(confs_asr),
        "words": len(paraules),
        "lines": len(analisi.lines),
    }
    if alineacio is not None:
        lletra["matched_ratio"] = alineacio["aparellades"]
        lletra["discarded_lines"] = len(alineacio["descartades"])
        if paraules:
            lletra["timed_ratio"] = round(sum(p.conf is not None for p in paraules) / len(paraules), 3)

    acords = analisi.chords
    stats = {
        "v": VERSIO,
        "app_version": __version__,
        "device": {"type": perfil.device, "name": perfil.nom, "vram_gb": perfil.vram_gb, "threads": perfil.fils},
        "audio": {"duration_s": analisi.source.duration_s},
        "timing": {
            "total_s": total,
            "stages_s": temps,
            "cached": sorted(cached),
        },
        "lyrics": lletra,
        "chords": {
            "count": len(acords),
            "distinct": len({a.label for a in acords}),
            "mean_conf": _mitjana([a.conf for a in acords], [a.end - a.start for a in acords]),
            "vocabulary": vocabulari,
        },
        "key": {"label": analisi.key.clau, "confidence": round(analisi.key.confidence, 3),
                "capo": analisi.capo_suggerit} if analisi.key else None,
        "tempo": {"bpm": analisi.tempo.bpm,
                  "time_signature": "/".join(map(str, analisi.tempo.time_signature))} if analisi.tempo else None,
        "structure": {"sections": len(analisi.sections)},
        "models": {k: v for k, v in analisi.models.items()
                   if k not in ("device", "device_name", "lyrics_align", "lyrics_aparellades")},
        "warnings": list(analisi.avisos),
        "checks": {},
    }
    return stats
