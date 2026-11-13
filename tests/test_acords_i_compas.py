import numpy as np

from transcriptor.postprocess import chords_clean, meter
from transcriptor.vendor.btc import idx_a_acord


def _classe(etiqueta: str) -> int:
    return next(i for i in range(170) if idx_a_acord(i) == etiqueta)


def _probs(seq: list[tuple[str, int]], soroll: float = 0.0, seed: int = 0) -> np.ndarray:
    """Probabilitats sintètiques: `seq` = [(etiqueta Harte, trames)]."""
    rng = np.random.default_rng(seed)
    files = []
    for etiqueta, n in seq:
        p = np.full((n, 170), 1e-4, dtype=np.float32)
        p[:, _classe(etiqueta)] = 1.0
        files.append(p)
    p = np.concatenate(files)
    p += soroll * rng.random(p.shape).astype(np.float32)
    return p / p.sum(axis=1, keepdims=True)


def test_vocabulari_col_lapsa_septimes_en_majmin():
    etiquetes, m = chords_clean.vocabulari("majmin")
    assert "A7" not in etiquetes and "A" in etiquetes and "Am" in etiquetes
    assert m[_classe("A:7"), etiquetes.index("A")] > 0


def test_viterbi_elimina_espurnes_d_una_trama():
    per_trama = 0.1
    # 2 s de A, una trama espúria de C, 2 s de A, 2 s d'E
    probs = _probs([("A", 20), ("C", 1), ("A", 20), ("E", 20)])
    pulsacions = list(np.arange(0.0, 6.1, 0.5))
    etiquetes, col = chords_clean.vocabulari("majmin")
    vores = chords_clean.unitats(pulsacions, 6.1)
    pu = chords_clean.probabilitats_per_unitat(probs, per_trama, vores, col)
    cami = chords_clean.viterbi(pu, np.zeros(len(pu), dtype=bool))
    segs = chords_clean.segments(cami, etiquetes, vores, pu)
    assert [s["label"] for s in segs] == ["A", "E"]
    assert abs(segs[1]["start"] - 4.0) < 0.6


def test_compas_4_4_amb_inicis_erratics():
    pulsacions = list(np.arange(0.0, 64 * 0.5, 0.5))  # 64 pulsacions a 120 BPM
    # Inicis de compàs bons cada 4, més uns quants falsos
    inicis = [pulsacions[i] for i in range(0, 64, 4)] + [pulsacions[i] for i in (5, 22, 37)]
    canvis = [i % 8 == 0 for i in range(64)]
    r = meter.regularitza(pulsacions, sorted(inicis), canvis)
    assert r["time_signature"] == [4, 4]
    assert r["bpm"] == 120.0
    assert [b["beat"] for b in r["beats"][:8]] == [1, 2, 3, 4, 1, 2, 3, 4]


def test_compas_compost_6_8():
    # Corxeres a 200 BPM, Beat This! marca un inici cada 3; l'harmonia canvia cada 6
    pulsacions = list(np.arange(0.0, 96 * 0.3, 0.3))
    inicis = [pulsacions[i] for i in range(0, 96, 3)]
    canvis = [i % 6 == 0 for i in range(96)]
    r = meter.regularitza(pulsacions, inicis, canvis)
    assert r["time_signature"] == [6, 8]
    assert [b["beat"] for b in r["beats"][:7]] == [1, 2, 3, 4, 5, 6, 1]


def _p_unitat(seq: str, etiquetes: list[str], forca: float = 0.8) -> np.ndarray:
    """Probabilitats per pulsació: `seq` = etiquetes separades per espais (una per pulsació)."""
    p = np.full((len(seq.split()), len(etiquetes)), (1 - forca) / (len(etiquetes) - 1))
    for u, e in enumerate(seq.split()):
        p[u, etiquetes.index(e)] = forca
    return p


def _compas_4(n: int) -> list[dict]:
    return [{"t": i * 0.5, "bar": i // 4 + 1, "beat": i % 4 + 1} for i in range(n)]


def _acords(cami: np.ndarray, etiquetes: list[str]) -> str:
    return " ".join(etiquetes[c] for c in cami)


def test_viterbi_compas_porta_a_terra_el_canvi_que_arriba_tard():
    etiquetes, _ = chords_clean.vocabulari("majmin")
    pu = _p_unitat("A A A A A E E E E E E E", etiquetes, 0.5)
    cami = chords_clean.viterbi_compas(pu, _compas_4(12), 0)
    assert _acords(cami, etiquetes) == "A A A A E E E E E E E E"


def test_viterbi_compas_mante_acords_de_pas_i_mig_compas():
    etiquetes, _ = chords_clean.vocabulari("majmin")
    pas = "A A A A D E F#m E A A A A"
    assert _acords(chords_clean.viterbi_compas(_p_unitat(pas, etiquetes, 0.9), _compas_4(12), 0), etiquetes) == pas
    mig = "A A D D E E E E A A A A"
    assert _acords(chords_clean.viterbi_compas(_p_unitat(mig, etiquetes), _compas_4(12), 0), etiquetes) == mig


def test_viterbi_compas_absorbeix_un_temps_aillat():
    etiquetes, _ = chords_clean.vocabulari("majmin")
    pu = _p_unitat("A A A A A C A A E E E E", etiquetes, 0.6)
    assert _acords(chords_clean.viterbi_compas(pu, _compas_4(12), 0), etiquetes) == "A A A A A A A A E E E E"


def test_viterbi_compas_amb_anacrusi_i_compas_irregular():
    etiquetes, _ = chords_clean.vocabulari("majmin")
    # Unitat [0, p0), anacrusi de 2 pulsacions, un compàs de 2 i compassos de 4
    temps = [3, 4, 1, 2, 3, 4, 1, 2, 1, 2, 3, 4]
    beats = [{"t": 0.5 + i * 0.5, "bar": 0, "beat": b} for i, b in enumerate(temps)]
    pu = _p_unitat("N G G C C C C D D E E E E", etiquetes)
    cami = chords_clean.viterbi_compas(pu, beats, 1)
    assert _acords(cami, etiquetes) == "N G G C C C C D D E E E E"
