"""Contracte central: `SongAnalysis` (JSON versionat).

El `content` amb <ch>/<sec> és una vista derivada d'aquest objecte (render.py), no la font de veritat.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VERSIO = 1


class Font(BaseModel):
    url: str | None = None
    youtube_id: str | None = None
    fitxer: str | None = None
    duration_s: float


class Meta(BaseModel):
    title: str = ""
    artist: str = ""
    language: str = "ca"


class Tonalitat(BaseModel):
    tonic: str  # notació del projecte, amb sostinguts: "A", "F#"
    mode: Literal["major", "minor"]
    confidence: float

    @property
    def clau(self) -> str:
        """Format `key` del canconer: "A", "Am"."""
        return self.tonic + ("m" if self.mode == "minor" else "")


class Tempo(BaseModel):
    bpm: float
    time_signature: tuple[int, int] = (4, 4)


class Pulsacio(BaseModel):
    t: float
    bar: int  # 1-based; 0 = anacrusi (pulsacions abans del primer compàs)
    beat: int  # 1-based; beat 1 = inici de compàs


class Acord(BaseModel):
    start: float
    end: float
    label: str  # notació del projecte ("F#m7")
    raw: str  # etiqueta del model ("F#:min7")
    bar: int | None = None
    beat: int | None = None
    conf: float = 0.0


class Paraula(BaseModel):
    start: float
    end: float
    text: str  # tal com s'ha d'escriure (amb puntuació i majúscules)
    conf: float | None = None


class Linia(BaseModel):
    start: float
    end: float
    word_range: tuple[int, int]  # [inici, fi) sobre `words`
    section: int | None = None  # índex a `sections`


class Seccio(BaseModel):
    start: float
    end: float
    label: str  # tipus: "intro", "estrofa", "tornada", "pont", "instrumental", "outro"...
    name: str  # nom visible: "Estrofa 1", "Tornada"


class SongAnalysis(BaseModel):
    version: int = VERSIO
    source: Font
    meta: Meta = Field(default_factory=Meta)
    key: Tonalitat | None = None
    capo_suggerit: int = 0
    tempo: Tempo | None = None
    beats: list[Pulsacio] = Field(default_factory=list)
    chords: list[Acord] = Field(default_factory=list)
    words: list[Paraula] = Field(default_factory=list)
    lines: list[Linia] = Field(default_factory=list)
    sections: list[Seccio] = Field(default_factory=list)
    lyrics_source: Literal["user", "db", "lrclib", "whisper", "cap"] = "cap"
    models: dict[str, str] = Field(default_factory=dict)
    temps_etapes_s: dict[str, float] = Field(default_factory=dict)
    avisos: list[str] = Field(default_factory=list)  # coses a revisar (línies descartades...)


class ImportResult(BaseModel):
    """Mateixa forma que `ImportResult` de src/lib/importers/types.ts del canconer."""

    title: str
    artist: str
    key: str
    capo: int
    language: str
    tags: str = ""
    content: str
    youtubeUrl: str | None = None  # noqa: N815 — nom del canconer


# ─── Format compacte (el que viatja a l'API i es desa a la BD del canconer) ──────────────────
#
# Mateixa informació que `SongAnalysis`, però amb tuples en lloc d'objectes i temps en ms enters
# (unes 4 vegades més petit). Pèrdua: temps arrodonits al ms i confiances a 0,001.
#
#   beats:    {"dt": [ms des de l'anterior...], "downbeats": [índexs amb beat 1],
#              "beat_exceptions": {"índex": beat}}   ← només si la numeració no és consecutiva
#   chords:   [start_ms, end_ms, label, conf, índex de pulsació | null (, raw si ≠ label)]
#   words:    [start_ms, end_ms, text, conf | null]
#   lines:    [start_ms, end_ms, paraula_inici, paraula_fi, secció | null]
#   sections: [start_ms, end_ms, label, name]
#
# El `bar` de cada pulsació no es desa: és el nombre de pulsacions amb beat 1 fins a ella (0 =
# anacrusi). El `beat` es dedueix comptant des de l'últim inici de compàs; les pulsacions de
# l'anacrusi compten enrere des del numerador del compàs.

FORMAT_COMPACTE = 2


def _ms(t: float) -> int:
    return round(t * 1000)


def _s(ms: int) -> float:
    return ms / 1000


def _conf(c: float | None) -> float | None:
    return None if c is None else round(c, 3)


def _beats_deduits(n: int, downbeats: list[int], numerador: int) -> list[int]:
    beats = []
    primer = downbeats[0] if downbeats else n
    ultim = None
    db = set(downbeats)
    for i in range(n):
        if i in db:
            ultim = i
        if ultim is None:
            beats.append(numerador - (primer - i) + 1)
        else:
            beats.append(i - ultim + 1)
    return beats


def a_compacte(a: SongAnalysis) -> dict:
    numerador = a.tempo.time_signature[0] if a.tempo else 4
    temps = [_ms(b.t) for b in a.beats]
    downbeats = [i for i, b in enumerate(a.beats) if b.beat == 1]
    deduits = _beats_deduits(len(a.beats), downbeats, numerador)
    excepcions = {str(i): b.beat for i, b in enumerate(a.beats) if b.beat != deduits[i]}
    beats: dict = {"dt": [t - (temps[i - 1] if i else 0) for i, t in enumerate(temps)], "downbeats": downbeats}
    if excepcions:
        beats["beat_exceptions"] = excepcions

    # Índex de la pulsació de cada acord, a partir del seu (bar, beat)
    idx_pulsacio = {(b.bar, b.beat): i for i, b in reversed(list(enumerate(a.beats)))}
    acords = []
    for c in a.chords:
        fila = [_ms(c.start), _ms(c.end), c.label, _conf(c.conf),
                idx_pulsacio.get((c.bar, c.beat)) if c.bar is not None else None]
        if c.raw != c.label:
            fila.append(c.raw)
        acords.append(fila)

    return {
        "v": FORMAT_COMPACTE,
        "source": a.source.model_dump(exclude_none=True),
        "meta": a.meta.model_dump(),
        "key": a.key.model_dump() if a.key else None,
        "capo": a.capo_suggerit,
        "tempo": {"bpm": a.tempo.bpm, "time_signature": list(a.tempo.time_signature)} if a.tempo else None,
        "beats": beats,
        "chords": acords,
        "words": [[_ms(w.start), _ms(w.end), w.text, _conf(w.conf)] for w in a.words],
        "lines": [[_ms(l.start), _ms(l.end), l.word_range[0], l.word_range[1], l.section] for l in a.lines],
        "sections": [[_ms(s.start), _ms(s.end), s.label, s.name] for s in a.sections],
        "lyrics_source": a.lyrics_source,
        "models": a.models,
        "stage_times_s": a.temps_etapes_s,
        "warnings": a.avisos,
    }


def de_compacte(d: dict) -> SongAnalysis:
    if d.get("v") != FORMAT_COMPACTE:
        raise ValueError(f"Format compacte desconegut: {d.get('v')}")
    tempo = Tempo(bpm=d["tempo"]["bpm"], time_signature=tuple(d["tempo"]["time_signature"])) \
        if d.get("tempo") else None
    numerador = tempo.time_signature[0] if tempo else 4
    b = d["beats"]
    temps, acumulat = [], 0
    for dt in b["dt"]:
        acumulat += dt
        temps.append(acumulat)
    numeros = _beats_deduits(len(temps), b["downbeats"], numerador)
    for i, beat in b.get("beat_exceptions", {}).items():
        numeros[int(i)] = beat
    pulsacions, compas = [], 0
    for t, beat in zip(temps, numeros):
        if beat == 1:
            compas += 1
        pulsacions.append(Pulsacio(t=_s(t), bar=compas, beat=beat))

    acords = []
    for fila in d["chords"]:
        ini, fi, label, conf, idx = fila[:5]
        p = pulsacions[idx] if idx is not None else None
        acords.append(Acord(start=_s(ini), end=_s(fi), label=label, raw=fila[5] if len(fila) > 5 else label,
                            bar=p.bar if p else None, beat=p.beat if p else None, conf=conf))
    return SongAnalysis(
        version=VERSIO,
        source=Font(**d["source"]),
        meta=Meta(**d["meta"]),
        key=Tonalitat(**d["key"]) if d.get("key") else None,
        capo_suggerit=d.get("capo", 0),
        tempo=tempo,
        beats=pulsacions,
        chords=acords,
        words=[Paraula(start=_s(a), end=_s(b_), text=t, conf=c) for a, b_, t, c in d["words"]],
        lines=[Linia(start=_s(a), end=_s(b_), word_range=(w0, w1), section=s) for a, b_, w0, w1, s in d["lines"]],
        sections=[Seccio(start=_s(a), end=_s(b_), label=l, name=n) for a, b_, l, n in d["sections"]],
        lyrics_source=d["lyrics_source"],
        models=d.get("models", {}),
        temps_etapes_s=d.get("stage_times_s", {}),
        avisos=d.get("warnings", []),
    )
