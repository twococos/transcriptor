import json
from pathlib import Path

import numpy as np
import pytest

from transcriptor.postprocess import meter, pulsacions

DADES = Path(__file__).parent / "dades" / "ritme"  # rhythm.json crus de l'app (Beat This! final0)


def _graella(n: int, t: float = 0.5, inici: float = 1.0) -> list[float]:
    return [round(inici + k * t, 3) for k in range(n)]


def _inicis(p: list[float]) -> list[float]:
    return p[::4]


def test_graella_perfecta_no_es_toca():
    p = _graella(80)
    r = pulsacions.corregeix(p, _inicis(p))
    assert r["pulsacions"] == p
    assert r["correccions"] == []


def test_pulsacio_falsa_desapareix():
    p = _graella(80)
    fals = sorted(p + [p[40] + 0.12])
    r = pulsacions.corregeix(fals, _inicis(p))
    assert r["pulsacions"] == p
    assert [c["tipus"] for c in r["correccions"]] == ["forat"]


def test_tram_curt_a_doble_tempo_es_regularitza():
    p = _graella(80)
    rapid = sorted(p + [round(t + 0.25, 3) for t in p[40:42]])  # dues pulsacions de més, a corxeres
    r = pulsacions.corregeix(rapid, _inicis(p))
    assert np.allclose(r["pulsacions"], p)


def test_forat_sense_pulsacions_s_omple():
    p = _graella(80)
    r = pulsacions.corregeix(p[:40] + p[43:], _inicis(p))
    assert np.allclose(r["pulsacions"], p)


def test_ritardando_que_no_encaixa_es_respecta():
    # Calderó: després d'una pausa de 1.3 pulsacions la cançó continua amb una altra fase
    p = _graella(40) + _graella(40, inici=_graella(40)[-1] + 0.65)
    r = pulsacions.corregeix(p, _inicis(p))
    assert r["pulsacions"] == p


def test_tram_llarg_a_meitat_de_tempo():
    p = _graella(120)
    lent = p[:80] + p[80::2]  # l'última (p[119]) no hi és
    r = pulsacions.corregeix(lent, _inicis(p))
    assert np.allclose(r["pulsacions"], p[:119])
    assert r["correccions"][0]["tipus"] == "octava"


def _real(nom: str) -> tuple[np.ndarray, dict]:
    ritme = json.loads((DADES / f"{nom}.json").read_text(encoding="utf-8"))
    r = pulsacions.corregeix(ritme["pulsacions"], ritme["inicis_compas"])
    return np.asarray(r["pulsacions"]), r


def _intervals(p: np.ndarray, t0: float, t1: float) -> np.ndarray:
    dins = (p[:-1] >= t0) & (p[1:] <= t1)
    return np.diff(p)[dins]


# (cançó, període de pulsació real, finestres amb errors de Beat This! segons la revisió a mà)
CASOS = [
    ("comedia", 0.333, [(40, 80), (140, 160)]),
    ("torno", 0.469, [(55, 62)]),
    ("tiets", 0.39, [(84, 92), (93.4, 110)]),
    ("lladre", 0.527, [(44, 62), (195, 215), (245, 275)]),
    ("efaristo", 0.577, [(0, 170)]),
    ("llovera", 0.341, [(0.3, 10), (55, 65), (115, 175)]),  # 0:00.14 és falsa, però abans de tot
    ("esbarzers", 0.417, [(225, 245)]),
]


@pytest.mark.parametrize("nom,periode,finestres", CASOS)
def test_cancons_reals_amb_graella_regular(nom, periode, finestres):
    # Una pulsació falsa o perduda desvia l'interval un 40-50 %; el jitter de Beat This! (temps
    # quantitzats a 0.02 s, algun temps avançat 0.04 s) arriba al 15 %
    p, _ = _real(nom)
    for t0, t1 in finestres:
        ibi = _intervals(p, t0, t1)
        assert len(ibi) > 0
        assert np.abs(ibi / periode - 1).max() < 0.18, (nom, t0, t1)


def test_mari_carmen_no_es_toca():
    # Els compassos irregulars de 1:46 i 2:13 són de la cançó: la graella de pulsacions és regular
    _, r = _real("carmen")
    assert r["correccions"] == []


def test_6_8_es_queda_a_corxeres():
    # T'he trobat a faltar: Beat This! compta corxeres (231 BPM) i meter.py en fa un 6/8
    p, _ = _real("trobat")
    assert 0.24 < np.median(np.diff(p)) < 0.28


def test_comedia_el_primer_temps_quadra_despres_dels_fills():
    # Error 2: abans, dues pulsacions falses a 0:52.7 desplaçaven el compàs fins a 1:13
    p, r = _real("comedia")
    compas = meter.regularitza(list(p), r["inicis_compas"], [False] * len(p))
    temps = {round(b["t"], 2): b["beat"] for b in compas["beats"]}
    inicis = [t for t in temps if 52 < t < 74 and temps[t] == 1]
    assert inicis[0] == pytest.approx(52.10, abs=0.03)
    assert inicis[-1] == pytest.approx(73.42, abs=0.03)
    assert np.allclose(np.diff(inicis), 4 / 3, atol=0.06)
