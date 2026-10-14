from transcriptor import merge, render, structure
from transcriptor.stages.lyrics_align import alinea
from transcriptor.stages.lyrics_source import text_de_content
from transcriptor.text import linies_de_text


def _asr(paraules: list[str], inici: float = 1.0, pas: float = 0.5) -> list[dict]:
    return [{"start": inici + i * pas, "end": inici + i * pas + 0.4, "text": p, "conf": 0.9}
            for i, p in enumerate(paraules)]


def test_alineacio_transfereix_temps_amb_errors_d_asr():
    linies = linies_de_text("L'avi Siset em parlava\nde bon matí al portal")
    # L'ASR parteix "L'avi" i s'equivoca a "parlava"
    asr = _asr(["L", "'avi", "Siset", "em", "parlaba", "de", "bon", "matí", "al", "portal"])
    r = alinea(linies, asr, 20.0)
    textos = [p["text"] for p in r["paraules"]]
    assert textos == ["L'avi", "Siset", "em", "parlava", "de", "bon", "matí", "al", "portal"]
    assert r["paraules"][0]["start"] == 1.0 and r["paraules"][0]["end"] == 1.9
    assert r["paraules"][4]["start"] == 3.5  # "de"
    assert r["linies"] == [[0, 4], [4, 9]]


def test_alineacio_interpola_paraules_no_cantades_per_l_asr():
    linies = linies_de_text("un dos tres quatre cinc")
    asr = _asr(["un", "dos"]) + _asr(["cinc"], inici=5.0)
    r = alinea(linies, asr, 10.0)
    t = [p["start"] for p in r["paraules"]]
    assert t == sorted(t)
    assert r["paraules"][2]["conf"] is None and 1.5 < t[2] < 5.0


def test_text_de_content_treu_acords_i_seccions():
    c = "<sec>Estrofa 1</sec>\n<ch>Am</ch>L'avi Sis<ch>E</ch>et\n<ch>A</ch>    <ch>E</ch>"
    assert text_de_content(c) == "L'avi Siset"


def test_linia_amb_acords():
    assert render.linia_amb_acords("L'avi Siset", [[0, "Am"], [8, "E"]]) == "<ch>Am</ch>L'avi Si<ch>E</ch>set"
    assert render.linia_amb_acords("dir,", [[0, "F#m"], [10, "D"]]) == "<ch>F#m</ch>dir, <ch>D</ch>"


def _escenari():
    """Intro instrumental, estrofa, tornada, estrofa, tornada (temps en segons, compàs de 2 s)."""
    beats = [{"t": i * 0.5, "bar": i // 4 + 1, "beat": i % 4 + 1} for i in range(200)]
    text = ("Primer vers de la estrofa\nSegon vers molt diferent\n"
            "Aquesta es la tornada\nque es repeteix sempre\n"
            "Tercer vers de la cançó\nQuart vers per acabar\n"
            "Aquesta es la tornada\nque es repeteix sempre")
    linies = linies_de_text(text)
    paraules, rangs, t = [], [], 8.0
    for k, l in enumerate(linies):
        inici = len(paraules)
        for p in l:
            paraules.append({"start": t, "end": t + 0.4, "text": p, "conf": 0.9})
            t += 0.5
        rangs.append([inici, len(paraules)])
        t += 1.0 if k % 2 == 0 else 3.0  # pausa més llarga entre parells de línies
    acords = [{"start": 0.0, "end": 4.0, "label": "A"}, {"start": 4.0, "end": 8.0, "label": "E"}]
    for linia_ini, (a, b) in zip(range(len(rangs)), rangs):
        acords.append({"start": paraules[a]["start"], "end": paraules[b - 1]["end"],
                       "label": "D" if linia_ini in (2, 3, 6, 7) else "A"})
    return paraules, rangs, acords, beats, t


def test_merge_estructura_i_render():
    paraules, rangs, acords, beats, durada = _escenari()
    elements = merge.colloca(paraules, rangs, acords, beats, durada)
    assert elements[0]["tipus"] == "instrumental"
    seccions = structure.detecta(elements, durada, 2.0)
    noms = [s["name"] for s in seccions]
    assert noms == ["Intro", "Estrofa 1", "Tornada", "Estrofa 2", "Tornada"]
    content = render.content(elements, seccions)
    linies = content.split("\n")
    assert linies[0] == "<sec>Intro</sec>"
    assert linies[1] == "<ch>A</ch>    <ch>E</ch>"
    assert "<ch>D</ch>Aquesta es la tornada" in content
    assert "" not in linies


def test_render_amb_capo_transposa_a_formes():
    elements = [{"tipus": "linia", "start": 0, "end": 1, "text": "hola", "acords": [[0, "A#", 0.0]]}]
    seccions = [{"name": "Estrofa 1", "elements": [0]}]
    assert render.content(elements, seccions, capo=1) == "<sec>Estrofa 1</sec>\n<ch>A</ch>hola"
