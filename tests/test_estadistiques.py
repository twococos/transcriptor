"""Estadístiques de la feina (estadistiques.py), el seu text a l'app (app/detalls.py) i les classificacions."""

import json

from transcriptor import estadistiques, fetes
from transcriptor.app import classificacions, detalls
from transcriptor.device import Perfil
from transcriptor.schema import Acord, Font, Paraula, SongAnalysis, Tempo, Tonalitat

PERFIL = Perfil(device="cpu", nom="Intel i7-6700", vram_gb=0, fils=4, whisper_compute_type="int8",
                separador="htdemucs", demucs_shifts=0)


def _analisi(**kw) -> SongAnalysis:
    return SongAnalysis(
        source=Font(duration_s=200.0),
        key=Tonalitat(tonic="A", mode="minor", confidence=0.7412),
        tempo=Tempo(bpm=96.0, time_signature=(4, 4)),
        chords=[Acord(start=0, end=3, label="Am", raw="Am", conf=0.9),
                Acord(start=3, end=4, label="G", raw="G", conf=0.5)],
        words=[Paraula(start=0, end=1, text="Bon", conf=0.9), Paraula(start=1, end=2, text="dia", conf=None)],
        lyrics_source="lrclib",
        models={"separation": "htdemucs", "lyrics_align": "transfer-asr", "device": "cpu", "device_name": "x"},
        temps_etapes_s={"separate": 120.0, "lyrics_asr": 200.5, "total": 340.2},
        avisos=["Una línia descartada"],
        **kw,
    )


def test_estadistiques_amb_lletra_coneguda():
    al = {"aparellades": 0.875, "descartades": ["la la la"]}
    s = estadistiques.calcula(_analisi(), PERFIL, {"fetch"}, al, [0.8, 0.6], "sevenths")
    assert s["v"] == 1 and s["audio"]["duration_s"] == 200.0
    assert s["timing"] == {"total_s": 340.2, "stages_s": {"separate": 120.0, "lyrics_asr": 200.5},
                           "cached": ["fetch"]}
    assert s["lyrics"]["matched_ratio"] == 0.875 and s["lyrics"]["discarded_lines"] == 1
    assert s["lyrics"]["timed_ratio"] == 0.5 and s["lyrics"]["asr_mean_conf"] == 0.7
    # Confiança dels acords ponderada per durada: (0,9·3 + 0,5·1) / 4
    assert s["chords"] == {"count": 2, "distinct": 2, "mean_conf": 0.8, "vocabulary": "sevenths"}
    assert s["key"]["label"] == "Am" and s["tempo"]["time_signature"] == "4/4"
    assert "device" not in s["models"] and s["models"]["separation"] == "htdemucs"
    json.dumps(s)  # ha de viatjar com a JSON


def test_estadistiques_amb_whisper_no_tenen_aparellament():
    s = estadistiques.calcula(_analisi(), PERFIL, set(), None, [], "majmin")
    assert "matched_ratio" not in s["lyrics"] and s["lyrics"]["asr_mean_conf"] is None
    assert s["timing"]["cached"] == []


def test_detalls_agrupa_i_mostra_els_camps_nous():
    s = estadistiques.calcula(_analisi(), PERFIL, {"separate"}, {"aparellades": 0.875, "descartades": []},
                              [0.8], "sevenths")
    s["timing"]["wall_s"] = 351
    s["checks"] = {"chords_web": {"site": "acordscatala", "agreement": 0.9}}
    g = dict(detalls.grups(s))
    assert ("Total", "5:51") in g["Temps"]
    assert ("De la cache", "separar la veu") in g["Temps"]
    assert ("Text ancorat a l'àudio", "88 %") in g["Lletra"]
    assert g["Màquina"][0] == ("Dispositiu", "CPU — Intel i7-6700 (4 fils)")
    assert ("To", "Am · confiança 74 %") in g["Música"]
    assert ("checks.chords_web.site", "acordscatala") in g["Altres"]
    assert all(not k.startswith(("timing.", "lyrics.", "v")) for k, _ in g["Altres"])


def test_stats_de_cancons_antigues(tmp_path, monkeypatch):
    monkeypatch.setenv("TX_HOME", str(tmp_path))
    a = _analisi()
    a.models["lyrics_aparellades"] = "0.9"
    fetes.desa(1, {"title": "Vella"}, a.model_dump_json(), None, 300)
    fetes.desa(2, {"title": "Nova"}, a.model_dump_json(), None, 300, stats={"v": 1, "checks": {}})
    vella, nova = sorted(fetes.llista(), key=lambda f: f.titol, reverse=True)
    assert vella.stats is None and nova.stats == {"v": 1, "checks": {}}
    s = fetes.stats_de(vella)
    assert s["lyrics"]["matched_ratio"] == 0.9 and s["timing"]["total_s"] == 340.2
    assert dict(detalls.grups(s))["Lletra"][0] == ("Font", "LRCLIB")


def _taula(rank_me, top_me=False, songs=10):
    return {"top": [{"rank": 1, "worker_id": 1, "name": "A", "value": 10, "me": top_me}],
            "me": {"rank": rank_me, "value": 5, "songs": songs}}


def test_classificacions_podis_i_millores():
    abans = {"periods": {"all": {"songs": _taula(4), "total_time": _taula(2), "speed": _taula(None, songs=2)}}}
    ara = {"periods": {"all": {"songs": _taula(3), "total_time": _taula(2), "speed": _taula(None, songs=2)},
                       "month": {"songs": _taula(1, True), "total_time": _taula(5), "speed": _taula(None)}}}
    assert classificacions.destacades(ara) == [(1, "Ets 1r en cançons transcrites aquest mes"),
                                               (2, "Ets 2n en temps transcrivint"),
                                               (3, "Ets 3r en cançons transcrites")]
    assert classificacions.millores(abans, ara) == ["Has pujat al 3r lloc en cançons transcrites",
                                                    "Has pujat al 1r lloc en cançons transcrites aquest mes"]
    assert classificacions.millores(None, ara) == []
    assert classificacions.valor("speed", 72) == "1:12 per minut de cançó"
    assert classificacions.valor("total_time", 3 * 3600 + 120) == "3 h 2 min"
    assert classificacions.valor("songs", 1) == "1 cançó"
    assert [classificacions.ordinal(n) for n in (1, 2, 3, 4, 5, 11)] == ["1r", "2n", "3r", "4t", "5è", "11è"]
