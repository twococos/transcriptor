from transcriptor.notation import de_harte, majmin, transposa
from transcriptor.postprocess.key import clau, estima, suggereix_capo


def test_de_harte_segons_nivell():
    assert de_harte("A:min7", "majmin") == "Am"
    assert de_harte("A:min7", "sevenths") == "Am7"
    assert de_harte("Bb:maj7", "sevenths") == "A#maj7"
    assert de_harte("E:hdim7", "sevenths") == "Em7b5"
    assert de_harte("C:sus4", "sevenths") == "C"
    assert de_harte("C:sus4", "full") == "Csus4"
    assert de_harte("N") is None


def test_majmin_i_transport():
    assert majmin("F#m7") == (6, "min")
    assert majmin("Bbmaj7") == (10, "maj")
    assert majmin("Bdim") == (11, "min")
    assert transposa("A#", -1) == "A"
    assert transposa("F#m7/C#", 2) == "G#m7/D#"


def _seq(acords, durada=2.0):
    return [{"start": i * durada, "end": (i + 1) * durada, "label": a} for i, a in enumerate(acords)]


def test_tonalitat_menor_i_major():
    estaca = estima(_seq(["Am", "E", "Am", "E", "Dm", "E", "Am", "F", "E", "Am"] * 3))
    assert clau(estaca) == "Am"
    bon_dia = estima(_seq(["A", "E", "F#m", "C#m", "D", "A", "Bm", "E"] * 3))
    assert clau(bon_dia) == "A"


def test_capo_suggerit():
    assert suggereix_capo({"tonic": "A#", "mode": "major"}) == 1  # "La gent que estimo": A amb capo 1
    assert suggereix_capo({"tonic": "A", "mode": "major"}) == 0
    assert suggereix_capo({"tonic": "G#", "mode": "minor"}) == 4  # → Em
