from transcriptor import merge, render
from transcriptor.postprocess import seccions


def _escenari():
    """Compàs de 4/4 de 2 s. Intro (0-8), estrofa amb anacrusi (veu a 7.5), tornada, un instrumental
    d'un compàs (24-26) i una altra estrofa."""
    beats = [{"t": i * 0.5, "bar": i // 4 + 1, "beat": i % 4 + 1} for i in range(80)]
    intro = {"tipus": "instrumental", "start": 0.0, "end": 8.0, "acords": [["A", 0.0], ["E", 4.0]]}
    intro["pulsacions"] = merge._pulsacions(intro["acords"], beats, 7.5, 0.25)
    zona = {"tipus": "instrumental", "start": 24.0, "end": 26.0, "acords": [["G", 24.0]]}
    zona["pulsacions"] = merge._pulsacions(zona["acords"], beats, 26.1, 0.25)
    elements = [
        intro,
        {"tipus": "linia", "start": 7.5, "end": 15.0, "word_range": [0, 3], "text": "hola que tal",
         "acords": [[5, "D", 8.0]]},
        {"tipus": "linia", "start": 16.2, "end": 23.0, "word_range": [3, 5], "text": "la tornada", "acords": []},
        zona,
        {"tipus": "linia", "start": 26.1, "end": 31.0, "word_range": [5, 7], "text": "adeu siau",
         "acords": [[0, "A", 26.0]]},
    ]
    seccs = [{"label": l, "name": l, "elements": [i]}
             for i, l in enumerate(["Intro", "Estrofa", "Tornada", "Instrumental", "Estrofa"])]
    acords = [{"start": a, "end": b, "label": l}
              for a, b, l in [(0, 4, "A"), (4, 8, "E"), (8, 24, "D"), (24, 26, "G"), (26, 32, "A")]]
    return elements, seccs, beats, acords


def test_seccions_contigues_a_terra_i_amb_llargades_rodones():
    elements, seccs, beats, acords = _escenari()
    els, sec = seccions.quadra(elements, seccs, beats, acords, 40.0)
    assert [s["name"] for s in sec] == ["Intro", "Estrofa 1", "Tornada", "Estrofa 2"]
    # L'anacrusi (veu a 7.5) no mou la frontera; l'instrumental d'un compàs no és secció, i passar-lo
    # a l'estrofa següent fa que la tornada i l'estrofa tinguin 4 compassos
    assert [(s["start"], s["end"]) for s in sec] == [(0.0, 8.0), (8.0, 16.0), (16.0, 24.0), (24.0, 32.0)]
    assert els[sec[1]["elements"][0]]["text"] == "hola que tal"
    estrofa2 = [els[i] for i in sec[3]["elements"]]
    assert [e["tipus"] for e in estrofa2] == ["instrumental", "linia"]


def test_acord_despres_del_titol_de_seccio_encara_que_ja_soni():
    elements, seccs, beats, acords = _escenari()
    els, sec = seccions.quadra(elements, seccs, beats, acords, 40.0)
    content = render.content(els, sec)
    assert "<sec>Tornada</sec>\n<ch>D</ch>la tornada" in content
    assert "<sec>Estrofa 1</sec>\nhola <ch>D</ch>que tal" in content  # anacrusi: l'acord ja hi és


def test_zona_instrumental_partida_per_una_frontera():
    beats = [{"t": i * 0.5, "bar": i // 4 + 1, "beat": i % 4 + 1} for i in range(80)]
    zona = {"tipus": "instrumental", "start": 0.0, "end": 16.0, "acords": [["A", 0.0], ["E", 8.0], ["D", 10.0]]}
    zona["pulsacions"] = merge._pulsacions(zona["acords"], beats, 16.0, 0.25)
    linia = {"tipus": "linia", "start": 16.0, "end": 23.0, "word_range": [0, 2], "text": "ara canto",
             "acords": [[0, "A", 16.0]]}
    acords = [{"start": 0, "end": 8, "label": "A"}, {"start": 8, "end": 10, "label": "E"},
              {"start": 10, "end": 16, "label": "D"}, {"start": 16, "end": 24, "label": "A"}]
    # structure.detecta hauria fet una intro de 8 compassos; aquí la frontera candidata és a mitja zona
    seccs = [{"label": "Intro", "name": "Intro", "elements": [0]}, {"label": "Estrofa", "name": "Estrofa",
                                                                      "elements": [1]}]
    els, sec = seccions.quadra([zona, linia], seccs, beats, acords, 30.0)
    assert [(s["start"], s["end"]) for s in sec] == [(0.0, 16.0), (16.0, 24.0)]
    # La frontera no es mou: la línia comença a terra
    assert [e["tipus"] for e in els] == ["instrumental", "linia"]
    t0 = seccions._talla(zona, 8.0, 16.0, lambda t: "A")
    assert t0["acords"][0] == ["E", 8.0] and t0["pulsacions"][0][2] == "E"
    t1 = seccions._talla(zona, 9.0, 16.0, lambda t: "E")
    assert t1["pulsacions"][0][2] == "E" and t1["acords"][0] == ["E", 9.0]


def _cas(trams: list[tuple], compassos: int = 40):
    """Compàs de 4/4 de 2 s. `trams`: (etiqueta, compàs d'inici, compàs de fi, acords) en ordre. Un
    tram amb lletra té una línia per cada 4 compassos (la veu acaba un temps abans de la fi); un
    instrumental, una zona amb els acords [(etiqueta, compàs)]."""
    beats = [{"t": i * 0.5, "bar": i // 4 + 1, "beat": i % 4 + 1} for i in range(compassos * 4)]
    elements, seccs, acords = [], [], []
    for etiqueta, a, b, acs in trams:
        idx = []
        if etiqueta in ("Intro", "Instrumental", "Solo", "Outro"):
            z = {"tipus": "instrumental", "start": 2.0 * a, "end": 2.0 * b,
                 "acords": [[et, 2.0 * c] for et, c in acs]}
            z["pulsacions"] = merge._pulsacions(z["acords"], beats, 2.0 * b, 0.25)
            idx.append(len(elements))
            elements.append(z)
        else:
            for k, c in enumerate(range(a, b, 4)):
                fi = min(c + 4, b)
                idx.append(len(elements))
                elements.append({"tipus": "linia", "start": 2.0 * c, "end": 2.0 * fi - 0.5,
                                 "word_range": [k, k + 1], "text": f"{etiqueta} {c}",
                                 "acords": [[0, et, 2.0 * cc] for et, cc in acs if c <= cc < fi][:1]})
        seccs.append({"label": etiqueta, "name": etiqueta, "elements": idx})
        acords += [{"start": 2.0 * c, "label": et} for et, c in acs]
    acords.sort(key=lambda x: x["start"])
    for x, y in zip(acords, acords[1:] + [{"start": 2.0 * compassos}]):
        x["end"] = y["start"]
    return elements, seccs, beats, acords


def _quadra(trams, **kw):
    elements, seccs, beats, acords = _cas(trams)
    for s in seccs:
        s.update(kw.get(s["label"], {}))
    fi = 2.0 * trams[-1][2]
    els, sec = seccions.quadra(elements, seccs, beats, acords, fi)
    return els, sec, [(s["name"], s["start"] / 2, s["end"] / 2) for s in sec]


def test_cua_curta_d_una_estrofa_no_es_un_instrumental():
    trams = [("Estrofa", 0, 6, [("D", 0)]), ("Instrumental", 6, 8, [("G", 6)]), ("Tornada", 8, 16, [("A", 8)])]
    els, sec, r = _quadra(trams)
    assert r == [("Estrofa 1", 0, 8), ("Tornada", 8, 16)]
    # L'acord de la cua va al final de l'última línia, després de la lletra
    assert "Estrofa 4<ch>D</ch>" not in render.content(els, sec)
    assert "\nEstrofa 4 <ch>G</ch>\n" in render.content(els, sec)


def test_zona_llarga_es_parteix_entre_cua_i_instrumental():
    zona = [("A", 7), ("E", 8), ("A", 10), ("E", 12), ("A", 14)]
    trams = [("Estrofa", 0, 7, [("D", 0)]), ("Instrumental", 7, 16, zona), ("Tornada", 16, 24, [("D", 16)])]
    _, _, r = _quadra(trams)
    assert r == [("Estrofa 1", 0, 8), ("Instrumental", 8, 16), ("Tornada", 16, 24)]


def test_solo_de_8_i_intro_de_4_es_queden():
    trams = [("Intro", 0, 4, [("A", 0), ("E", 2)]), ("Estrofa", 4, 12, [("D", 4)]),
             ("Solo", 12, 20, [("A", 12), ("E", 16)]), ("Tornada", 20, 28, [("D", 20)])]
    _, _, r = _quadra(trams)
    assert r == [("Intro", 0, 4), ("Estrofa 1", 4, 12), ("Solo", 12, 20), ("Tornada", 20, 28)]


def test_les_tabs_decideixen_si_un_interludi_curt_es_cua():
    trams = [("Estrofa", 0, 8, [("D", 0)]), ("Instrumental", 8, 12, [("A", 8), ("E", 10)]),
             ("Tornada", 12, 20, [("D", 12)])]
    _, _, r = _quadra(trams)
    assert [n for n, *_ in r] == ["Estrofa 1", "Instrumental", "Tornada"]
    _, _, r = _quadra(trams, Instrumental={"vot_cua": 1.0})
    assert r == [("Estrofa 1", 0, 12), ("Tornada", 12, 20)]
