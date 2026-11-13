"""Fonts d'acords externes: normalització, text pla, alineació, consens i seccions (casos sintètics)."""

import numpy as np

from transcriptor.config import Config
from transcriptor.fonts import aplica, normalitza, seccions as fonts_seccions
from transcriptor.fonts.alinea import Graella, alinea
from transcriptor.fonts.model import TabCrua
from transcriptor.fonts.text_pla import de_text
from transcriptor.pipeline import acords_de_graella
from transcriptor.postprocess import chords_clean


def test_normalitza_acords():
    casos = {"LAm": ("Am", "Am"), "Sol#m7": ("G#m7", "G#m7"), "Bb7": ("A#7", "A#7"), "C7M": ("Cmaj7", "Cmaj7"),
             "F#m7(b5)": ("F#m7b5", "F#m7b5"), "G/B": ("G/B", "G"), "Dsus": ("Dsus4", "D"),
             "E7(9)": ("E9", "E7"), "Bº": ("Bdim", "Bdim"), "(C)": ("C", "C"), "A-7": ("Am7", "Am7"),
             "Cadd9": ("Cadd9", "C"), "Do": ("C", "C")}
    for text, (escrit, classe) in casos.items():
        a = normalitza.acord(text)
        assert (a.escrit, a.classe) == (escrit, classe), text
    assert normalitza.acord("N.C.") is None
    assert normalitza.acord("x2") is None


def test_normalitza_seccions():
    tipus = {"Verse 2": "Estrofa", "Refrão": "Tornada", "Pre-Chorus": "Pre-tornada", "Estrofa II": "Estrofa",
             "Primeira Parte": "Estrofa", "Coda": "Outro", "Tornada x2": "Tornada", "Hola": None}
    for nom, t in tipus.items():
        assert normalitza.seccio(nom).tipus == t, nom


def test_text_pla():
    text = "Wonderwall - Oasis\nCapo 2\n\n[Verse 1]\nEm7      G\nToday is gonna be\n\n[Chorus]\nC  D  Em  x2\n"
    c = de_text(text)
    assert c.split("\n") == ["<sec>Verse 1</sec>", "<ch>Em7</ch>Today is <ch>G</ch>gonna be",
                             "<sec>Chorus</sec>", "<ch>C</ch>  <ch>D</ch>  <ch>Em</ch>"]


def test_repeticions_i_herencia():
    content = ("<sec>Verse</sec>\n<ch>C</ch>u u u\n<ch>G</ch>dos dos\n<sec>Chorus</sec>\n<ch>F</ch>tres tres\nx2\n"
               "<sec>Verse</sec>\nquatre quatre\ncinc cinc\n<sec>Chorus</sec>")
    t = normalitza.tab(TabCrua(lloc="x", url="", titol="", artista="", content=content))
    textos = [l.text for l in t.linies]
    assert textos == ["u u u", "dos dos", "tres tres", "tres tres", "quatre quatre", "cinc cinc", "tres tres", "tres tres"]
    heretades = [l for l in t.linies if l.heretada]
    assert [l.acords[0].escrit for l in heretades] == ["C", "G"]
    assert t.linies[-1].repeticio > 0  # el "[Chorus]" final copia la tornada


# Escenari sintètic: 8 compassos de 4/4 a 120 bpm, una línia de lletra per cada 2 compassos
ETIQUETES, _ = chords_clean.vocabulari("sevenths")
PARAULES_LINIA = [["hola", "que", "tal"], ["anem", "a", "casa"], ["molt", "be", "gracies"], ["adeu", "amic", "meu"]]


def _escenari(acords_audio: list[str], certesa: float = 0.5, segon: str | None = None):
    beats = [{"t": 0.5 * i, "bar": i // 4 + 1, "beat": i % 4 + 1} for i in range(32)]
    vores = np.array([0.5 * i for i in range(33)])
    p = np.full((32, len(ETIQUETES)), 0.01)
    for u in range(32):
        p[u, ETIQUETES.index(acords_audio[u // 4])] = certesa
        if segon:
            p[u, ETIQUETES.index(segon)] = 0.3
    p /= p.sum(axis=1, keepdims=True)
    paraules = []
    for k, linia in enumerate(PARAULES_LINIA):
        for j, w in enumerate(linia):
            t = 4.0 * k + 0.6 * j
            paraules.append({"start": t, "end": t + 0.5, "text": w})
    g = Graella(vores=vores, p_unitat=p, etiquetes=ETIQUETES, beats=beats, desfasament=0, paraules=paraules)
    gr = {"compas": {"beats": beats}, "p_unitat": p, "desfasament": 0, "etiquetes": ETIQUETES, "vores": vores}
    return g, gr


def _tab(lloc: str, acords: list[str], separador: str = "", seccions=("Verse", "Verse", "Chorus", "Chorus")) -> TabCrua:
    linies, ant = [], None
    for sec, a, ws in zip(seccions, acords, PARAULES_LINIA):
        if sec != ant:
            linies.append(f"<sec>{sec}</sec>")
            ant = sec
        linies.append(f"{separador}<ch>{a}</ch>{' '.join(ws)}")
    return TabCrua(lloc=lloc, url=lloc, titol="", artista="", content="\n".join(linies))


def _etiquetes_per_compas(segs: list[dict]) -> list[str]:
    return [next(s["label"] for s in segs if s["start"] <= 2.0 * b + 0.1 < s["end"]) for b in range(8)]


def _executa(tabs, audio, **kw):
    g, gr = _escenari(audio, **kw)
    segs = acords_de_graella(gr, Config())
    return segs, aplica.aplica(tabs, g, segs, lambda b: acords_de_graella(gr, Config(), b))


AUDIO = ["C", "C", "Am", "Am", "G", "G", "C", "C"]  # BTC diu Am on la cançó fa F


def test_sense_fonts_res_no_canvia():
    segs, r = _executa([], AUDIO)
    assert r.segs is segs and r.consens is None


def test_dues_fonts_independents_substitueixen():
    tabs = [_tab("ultimate_guitar", ["C", "F", "G", "C"]), _tab("cifraclub", ["C", "F", "G", "C"], separador=" ")]
    _, r = _executa(tabs, AUDIO, segon="F")
    assert _etiquetes_per_compas(r.segs) == ["C", "C", "F", "F", "G", "G", "C", "C"]
    assert r.resum["grups"] == 2
    assert any(s["origen"] == "substituit" for s in r.segs)


def test_una_font_no_venc_un_audio_clar():
    tabs = [_tab("acordscatala", ["C", "F", "G", "C"])]
    _, r = _executa(tabs, AUDIO, certesa=0.95)
    assert _etiquetes_per_compas(r.segs)[2:4] == ["Am", "Am"]


def test_copies_voten_com_una():
    tabs = [_tab("ultimate_guitar", ["C", "F", "G", "C"]), _tab("lacuerda", ["C", "F", "G", "C"])]
    _, r = _executa(tabs, AUDIO, segon="F")
    assert r.resum["grups"] == 1


def test_grafia_de_les_fonts():
    tabs = [_tab("ultimate_guitar", ["C", "Am", "G/B", "C"]), _tab("cifraclub", ["C", "Am", "G/B", "C"], separador=" ")]
    _, r = _executa(tabs, AUDIO)
    g = next(s for s in r.segs if s["start"] <= 8.1 < s["end"])
    assert (g["label"], g["raw"]) == ("G/B", "G")


def test_linia_sense_acords_no_opina():
    # La tab només escriu els acords de la primera línia: la resta no vol dir "el mateix acord"
    content = "<sec>Verse</sec>\n<ch>C</ch>hola que tal\nanem a casa\nmolt be gracies\nadeu amic meu"
    g, _ = _escenari(AUDIO)
    al = alinea(normalitza.tab(TabCrua(lloc="x", url="", titol="", artista="", content=content)), g)
    assert al is None or (al.k_unitat[8:] == -1).all()


def test_seccions_votades_per_les_tabs():
    tabs = [_tab("ultimate_guitar", ["C", "F", "G", "C"]), _tab("cifraclub", ["C", "F", "G", "C"], separador=" ")]
    g, gr = _escenari(AUDIO, segon="F")
    segs = acords_de_graella(gr, Config())
    r = aplica.aplica(tabs, g, segs, lambda b: acords_de_graella(gr, Config(), b))
    elements = [{"tipus": "linia", "start": 4.0 * k, "end": 4.0 * k + 1.8, "word_range": [3 * k, 3 * k + 3],
                 "text": " ".join(ws), "acords": []} for k, ws in enumerate(PARAULES_LINIA)]
    detectades = [{"label": "Estrofa", "name": "Estrofa 1", "elements": [0, 1, 2, 3], "start": 0, "end": 14}]
    noves, canvis = fonts_seccions.corregeix(elements, detectades, [(f.al, f.pes) for f in r.consens.fonts], g.vores)
    assert [(s["label"], s["elements"]) for s in noves] == [("Estrofa", [0, 1]), ("Tornada", [2, 3])]
    assert canvis == 2
