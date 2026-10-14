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
