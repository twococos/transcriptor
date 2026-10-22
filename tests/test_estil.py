"""Estil rítmic: empremta de groove (stages/groove.py) i classificador (postprocess/style.py)."""

import json

import numpy as np

from transcriptor.postprocess import style
from transcriptor.schema import Font, Groove, Ritme, SongAnalysis, a_compacte, de_compacte
from transcriptor.stages import groove

SR = groove.SR


def _beats(n_compassos: int, numerador: int, ibi: float, inici: float = 0.5) -> list[dict]:
    return [{"t": inici + i * ibi, "bar": i // numerador + 1, "beat": i % numerador + 1}
            for i in range(n_compassos * numerador + 1)]


def _cop(senyal: np.ndarray, t: float, freq: float | None, dur: float = 0.06, amp: float = 0.8) -> None:
    """Un atac: soroll (freq None) o una nota que s'apaga."""
    i = int(t * SR)
    n = min(int(dur * SR), len(senyal) - i)
    if n <= 0:
        return
    x = np.arange(n) / SR
    env = np.exp(-x / (dur / 4))
    rng = np.random.default_rng(int(t * 1000))
    so = rng.uniform(-1, 1, n) if freq is None else np.sin(2 * np.pi * freq * x)
    senyal[i:i + n] += amp * env * so


def test_empremta_troba_els_accents():
    # 4/4 a 120 bpm: baix als temps 1 i 3, caixa (soroll) als temps 2 i 4
    ibi = 0.5
    beats = _beats(8, 4, ibi)
    mescla = np.zeros(int((beats[-1]["t"] + 1) * SR), dtype=np.float32)
    for b in beats[:-1]:
        if b["beat"] in (1, 3):
            _cop(mescla, b["t"], 55, dur=0.25)
        else:
            _cop(mescla, b["t"], None, dur=0.08)
    e = groove.calcula(mescla, np.zeros_like(mescla), beats, (4, 4))
    assert e is not None
    assert e["slots_per_beat"] == 4 and len(e["mid"]) == 16
    greus, mitjos = np.array(e["low"]), np.array(e["mid"])
    assert {int(np.argmax(greus[:8])), int(np.argmax(greus[8:])) + 8} == {0, 8}
    assert mitjos[4] > 0.7 and mitjos[12] > 0.7
    assert mitjos[2] < 0.5 and mitjos[6] < 0.5
    assert e["regularitat"] < 0.01


def test_empremta_6_8_i_pocs_compassos():
    beats = _beats(6, 6, 0.25)
    mescla = np.zeros(int((beats[-1]["t"] + 1) * SR), dtype=np.float32)
    for b in beats[:-1]:
        _cop(mescla, b["t"], 220 if b["beat"] in (1, 4) else 330, dur=0.1)
    e = groove.calcula(mescla, np.zeros_like(mescla), beats, (6, 8))
    assert e["slots_per_beat"] == 2 and len(e["low"]) == 12
    assert e["swing"] is None
    # Menys de 4 compassos complets: no n'hi ha prou
    assert groove.calcula(mescla, np.zeros_like(mescla), _beats(2, 6, 0.25), (6, 8)) is None


def _empremta(low: str, mid: str, high: str, **extra) -> dict:
    v = lambda c: [int(x) / 9 for x in c]  # noqa: E731
    return {"low": v(low), "mid": v(mid), "high": v(high), "swing": 0.3, "regularitat": 0.0, **extra}


def test_classificador():
    # Contratemps a cada temps feble (ska) a tempo viu → reggae
    ska = _empremta("8000800080008000", "1090109010901090", "3090309030903090")
    assert style.classifica(ska, 150, (4, 4))["style"] == "reggae"
    # 3/4 amb baix al primer temps i acords al segon i al tercer → vals
    r = style.classifica(_empremta("900000000000", "200090009000", "200070007000"), 150, (3, 4))
    assert r["style"] == "vals"
    # 6/8: només hi competeixen els estils compostos
    r = style.classifica(_empremta("900000800000", "905070905070", "707070707070"), 70, (6, 8))
    assert r["style"].startswith("compost-")
    assert all(a[0].startswith("compost-") for a in r["alternatives"])
    # Swing clar → swing
    sw = _empremta("9000000080000000", "3000900030009000", "7000700070007000", swing=0.62)
    assert style.classifica(sw, 120, (4, 4))["style"] == "swing"
    # Tempo irregular o sense empremta → lliure
    assert style.classifica(dict(ska, regularitat=0.3), 150, (4, 4))["style"] == "lliure"
    assert style.classifica(None, None, (4, 4))["style"] == "lliure"


def test_classificador_probabilitats():
    r = style.classifica(_empremta("9000003080000300", "6050905060509050", "6060806060608060"), 110, (4, 4))
    assert r["style"] == "pop"
    assert 0 < r["confidence"] <= 1
    assert len(r["alternatives"]) == 3
    assert all(r["confidence"] >= p for _, p in r["alternatives"])
    assert r["style"] in style.STYLE_IDS


def test_compacte_amb_ritme():
    a = SongAnalysis(source=Font(duration_s=10.0),
                     rhythm=Ritme(style="rumba", confidence=0.6234, alternatives=[("pop", 0.2)],
                                  groove=Groove(slots_per_beat=4, low=[1.0, 0.123], mid=[0.5, 0.25],
                                                high=[0.0, 1.0])))
    c = json.loads(json.dumps(a_compacte(a)))
    assert c["rhythm"] == {"style": "rumba", "confidence": 0.623, "alternatives": [["pop", 0.2]],
                           "groove": {"slots_per_beat": 4, "low": [1.0, 0.12], "mid": [0.5, 0.25],
                                      "high": [0.0, 1.0]}}
    b = de_compacte(c)
    assert b.rhythm.style == "rumba" and b.rhythm.groove.low == [1.0, 0.12]
    # Sense estil (workers antics): el camp no hi és
    assert "rhythm" not in a_compacte(SongAnalysis(source=Font(duration_s=1.0)))
