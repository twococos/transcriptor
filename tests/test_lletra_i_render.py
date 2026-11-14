from transcriptor import merge, render, structure
from transcriptor.postprocess import rodes
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
    assert text_de_content("| <ch>A</ch>.   .   | <ch>E</ch>.   .   | (x2)\nhola") == "hola"


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
    # Un acord cada dos compassos: els temps queden comprimits
    assert linies[1] == "<ch>A</ch>| ' ' ' | ' ' ' <ch>E</ch>| ' ' ' | ' ' '"
    assert "<ch>D</ch>Aquesta es la tornada" in content
    assert "" not in linies
    # L'acord que ja sonava no es repeteix a l'inici de la línia següent
    assert "\nque es repeteix sempre\n" in content


def test_compassos_d_instrumental():
    puls = [[0, 1, "A"], [1, 2, None], [2, 3, "C#m"], [3, 4, "D"], [4, 1, None], [5, 2, None]]
    # C#m tapa dos temps: D es desplaça perquè no s'hi trepitgi. Sense barra final (la veu entra al temps 3)
    assert render.linies_compassos(puls) == ["<ch>A</ch>|   '   <ch>C#m</ch>'       <ch>D</ch>'   |   '"]
    # Zona que comença a mig compàs: el primer temps no és barra
    assert render.linies_compassos([[0, 3, "G"], [1, 4, None], [2, 1, "D"]]) == ["<ch>G</ch>' ' <ch>D</ch>|"]
    # Un sol acord no és una roda; la línia següent torna a escriure l'acord que sona
    puls = [[t, t % 4 + 1, "A" if t == 0 else None] for t in range(20)]
    linies = render.linies_compassos(puls)
    assert linies == ["<ch>A</ch>| ' ' ' | ' ' ' | ' ' ' | ' ' '", "<ch>A</ch>| ' ' '"]


def _puls(compassos: list[str | None], temps: int = 4) -> list[list]:
    """Un acord (o None, continua) per compàs."""
    return [[k * temps + q, q + 1, c if q == 0 else None] for k, c in enumerate(compassos) for q in range(temps)]


def test_roda_que_es_repeteix_s_escriu_una_vegada():
    # Uns compassos de E i després la roda G B Em C tres vegades, i un G per acabar
    linies = render.linies_compassos(_puls(["E", None, None, None] + ["G", "B", "Em", "C"] * 3 + ["G"]))
    assert linies == ["<ch>E</ch>| ' ' ' | ' ' ' | ' ' ' | ' ' '",
                      "<ch>G</ch>| ' ' ' <ch>B</ch>| ' ' ' <ch>Em</ch>| ' ' ' <ch>C</ch>| ' ' '  (x3)",
                      "<ch>G</ch>| ' ' '"]


def test_roda_de_dues_linies():
    roda = ["G", None, "B", None, "Em", None, "C", None]
    # A l'inici de la secció: una passada i "x2" sol a sota
    assert render.linies_compassos(_puls(roda * 2), inici_bloc=True) == [
        "<ch>G</ch>| ' ' ' | ' ' ' <ch>B</ch>| ' ' ' | ' ' '",
        "<ch>Em</ch>| ' ' ' | ' ' ' <ch>C</ch>| ' ' ' | ' ' '",
        "x2"]
    # Amb compassos abans, "x2" també els repetiria: s'escriu sencera, cada passada en línia nova
    linies = render.linies_compassos(_puls(["E", None] + roda * 2), inici_bloc=True)
    assert len(linies) == 5 and not any("x2" in l for l in linies)
    assert linies[1].startswith("<ch>G</ch>") and linies[3].startswith("<ch>G</ch>")


def test_roda_amb_variants_de_septima_i_canvis_a_mig_compas():
    puls = _puls(["A", "B", "A", "B7"])
    roda = rodes.trossos(puls)
    assert [t.vegades for t in roda] == [2]
    puls = [[t, t % 4 + 1, {0: "A", 2: "C#m", 3: "D"}.get(t % 8)] for t in range(24)]
    assert render.linies_compassos(puls) == ["<ch>A</ch>|   '   <ch>C#m</ch>'       <ch>D</ch>'   |   '   '   '  (x3)"]


def test_content_uneix_les_zones_seguides_d_una_seccio():
    beats = [{"t": float(i), "bar": i // 4 + 1, "beat": i % 4 + 1} for i in range(16)]
    a = {"tipus": "instrumental", "start": 0, "end": 6, "acords": [["E", 0.0]],
         "pulsacions": [[float(t), t % 4 + 1, "E" if t == 0 else None] for t in range(6)]}
    b = {"tipus": "instrumental", "start": 6, "end": 16, "acords": [["A", 8.0]],
         "pulsacions": [[float(t), t % 4 + 1, "A" if t == 8 else None] for t in range(6, 16)]}
    assert beats and render.content([a, b], [{"name": "Outro", "elements": [0, 1]}]) == (
        "<sec>Outro</sec>\n<ch>E</ch>| ' ' ' | ' ' ' <ch>A</ch>| ' ' ' | ' ' '")


def test_render_amb_capo_transposa_a_formes():
    elements = [{"tipus": "linia", "start": 0, "end": 1, "text": "hola", "acords": [[0, "A#", 0.0]]}]
    seccions = [{"name": "Estrofa 1", "elements": [0]}]
    assert render.content(elements, seccions, capo=1) == "<sec>Estrofa 1</sec>\n<ch>A</ch>hola"


def test_text_de_content_expandeix_repeticions():
    c = ("<sec>Estrofa 1</sec>\nu<ch>A</ch>n\ndos\nx2\n<sec>Tornada</sec>\n"
         "tres (x3)\nquatre\nbis")
    assert text_de_content(c).split("\n") == ["un", "dos", "un", "dos", "tres", "tres", "tres", "quatre",
                                             "tres", "tres", "tres", "quatre"]


def test_banc_desplega_les_repeticions():
    from transcriptor.bench import metrics
    c = "<sec>Solo</sec>\n<ch>G</ch>| ' ' ' <ch>C</ch>| ' ' '  (x2)\n<sec>Estrofa</sec>\nu<ch>A</ch>n\ndos\nx2"
    assert metrics.desplega_repeticions(c).split("\n") == [
        "<sec>Solo</sec>", "<ch>G</ch>| ' ' ' <ch>C</ch>| ' ' '", "<ch>G</ch>| ' ' ' <ch>C</ch>| ' ' '",
        "<sec>Estrofa</sec>", "u<ch>A</ch>n", "dos", "u<ch>A</ch>n", "dos"]
