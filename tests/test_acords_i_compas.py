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
