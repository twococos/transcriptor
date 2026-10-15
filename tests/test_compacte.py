"""Format compacte de l'anàlisi: ha de conservar tota la informació (temps al ms, confiances a 0,001)."""

import json

import pytest

from transcriptor.schema import (Acord, Font, Linia, Meta, Paraula, Pulsacio, Seccio, SongAnalysis, Tempo,
                                 Tonalitat, a_compacte, de_compacte)


def _analisi() -> SongAnalysis:
    # Anacrusi de 2 pulsacions (beats 3 i 4), dos compassos de 4 i un compàs irregular (1, 2, 4)
    numeros = [(0, 3), (0, 4), (1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (2, 2), (2, 4), (3, 1)]
    beats = [Pulsacio(t=round(0.5 + 0.6 * i, 3), bar=b, beat=n) for i, (b, n) in enumerate(numeros)]
    return SongAnalysis(
        source=Font(url="https://www.youtube.com/watch?v=abcdefghijk", youtube_id="abcdefghijk", duration_s=7.5),
        meta=Meta(title="Prova", artist="Ningú", language="ca"),
        key=Tonalitat(tonic="A", mode="minor", confidence=0.8123),
        capo_suggerit=2,
        tempo=Tempo(bpm=100.0, time_signature=(4, 4)),
        beats=beats,
        chords=[Acord(start=1.7, end=4.1, label="Am", raw="Am", bar=1, beat=1, conf=0.91234),
                Acord(start=4.1, end=5.3, label="F", raw="F:maj", bar=2, beat=1, conf=0.5),
                Acord(start=5.3, end=6.0, label="C", raw="C", bar=None, beat=None, conf=0.0)],
        words=[Paraula(start=1.71, end=2.0, text="Hola,", conf=0.95),
               Paraula(start=2.05, end=2.4, text="món", conf=None)],
        lines=[Linia(start=1.71, end=2.4, word_range=(0, 2), section=0)],
        sections=[Seccio(start=0.0, end=7.5, label="estrofa", name="Estrofa 1")],
        lyrics_source="lrclib",
        models={"chords": "btc"},
        temps_etapes_s={"total": 12.3},
        avisos=["una línia descartada"],
    )


def test_anada_i_tornada_conserva_tot():
    a = _analisi()
    c = json.loads(json.dumps(a_compacte(a)))  # passa per JSON com a l'API
    b = de_compacte(c)
    esperat = a.model_dump()
    esperat["chords"][0]["conf"] = 0.912
    assert b.model_dump() == esperat


def test_la_numeracio_consecutiva_no_es_desa():
    c = a_compacte(_analisi())
    assert c["beats"]["downbeats"] == [2, 6, 9]
    assert c["beats"]["beat_exceptions"] == {"8": 4}  # només el salt del compàs irregular
    assert c["beats"]["dt"][:3] == [500, 600, 600]
    assert c["chords"][1] == [4100, 5300, "F", 0.5, 6, "F:maj"]
    assert c["chords"][2] == [5300, 6000, "C", 0.0, None]


def test_format_desconegut():
    with pytest.raises(ValueError):
        de_compacte({"v": 1})
