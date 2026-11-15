"""Traça del depurador (traca.py): no canvia cap resultat i es pot desar en JSON."""

import json

import numpy as np

from transcriptor.config import Config
from transcriptor.fonts import aplica
from transcriptor.pipeline import acords_de_graella
from transcriptor.postprocess import rodes, seccions
from transcriptor.traca import Traca, net, top

from test_fonts import AUDIO, _escenari, _tab
from test_seccions import _cas


def test_net_dona_tipus_json():
    x = net({"a": np.float32(0.123456), "b": np.arange(3), "c": (1, np.int64(2)), "d": float("nan"), 3: True})
    assert x == {"a": 0.123, "b": [0, 1, 2], "c": [1, 2], "d": None, "3": True}
    assert top(np.array([[0.1, 0.7, 0.2]]), 2) == [[[1, 0.7], [2, 0.2]]]


def test_quadra_amb_traca_dona_el_mateix():
    trams = [("Intro", 0, 4, [("C", 0)]), ("Estrofa", 4, 10, [("D", 4)]), ("Instrumental", 10, 12, [("G", 10)]),
             ("Tornada", 12, 20, [("A", 12)])]
    sense = seccions.quadra(*_cas(trams), 40.0)
    t = Traca()
    amb = seccions.quadra(*_cas(trams), 40.0, traca=t)
    assert amb == sense
    q = t.passos["quadra"]
    assert [s["label"] for s in q["seccions"]] == ["Intro", "Estrofa", "Instrumental", "Tornada"]
    instr = q["seccions"][2]
    assert instr["eliminada"] and instr["compassos"] == 0
    assert q["cues"] and q["cues"][0]["acords"][0][0] == "G"  # la cua de l'estrofa va al final de la línia
    json.dumps(t.a_dict())


def test_aplica_amb_traca_dona_el_mateix():
    tabs = [_tab("ultimate_guitar", ["C", "F", "G", "C"]), _tab("cifraclub", ["C", "F", "G", "C"], separador=" ")]
    g, gr = _escenari(AUDIO, segon="F")
    segs = acords_de_graella(gr, Config())
    sense = aplica.aplica(tabs, g, [dict(s) for s in segs], lambda b: acords_de_graella(gr, Config(), b))
    t = Traca()
    amb = aplica.aplica(tabs, g, [dict(s) for s in segs], lambda b: acords_de_graella(gr, Config(), b), t)
    assert amb.segs == sense.segs and amb.fonts == sense.fonts
    f = t.passos["fonts"]
    assert [x["site"] for x in f["tabs"]] == ["ultimate_guitar", "cifraclub"]
    assert all(x["used"] and x["acords"] for x in f["tabs"])
    assert {a["escrit"] for a in f["tabs"][0]["acords"]} == {"C", "F", "G"}
    json.dumps(t.a_dict())


def _puls(compassos: list[list[str | None]]) -> list[list]:
    return [[4.0 * i + j, j + 1, et] for i, c in enumerate(compassos) for j, et in enumerate(c)]


def test_quasi_rodes():
    roda = [["G", None, None, None], ["B", None, None, None], ["Em", None, None, None], ["C", None, None, None]]
    variant = [["G", None, None, None], ["B", None, None, None], ["Em", None, "Am", None], ["C", None, None, None]]
    q = rodes.quasi_rodes(_puls(roda + variant + roda))
    assert len(q) == 1 and q[0]["P"] == 4 and q[0]["vegades"] == 3 and 0.75 <= q[0]["semblanca"] < 1
    # Si les repeticions són idèntiques ja es comprimeixen: no és una quasi-roda
    assert rodes.quasi_rodes(_puls(roda * 3)) == []
