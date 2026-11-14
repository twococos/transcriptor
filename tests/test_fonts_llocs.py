"""Parseig de les pàgines d'acords (fonts/llocs/), sense xarxa: pàgines reals desades a
tests/fixtures/fonts/ (les de GuitarTuna sense <script>/<style>/<svg>) i `http.obte` substituït."""

from __future__ import annotations

from pathlib import Path

import pytest

from transcriptor.fonts import http
from transcriptor.fonts.llocs import acordesweb, acordscatala, cifraclub, echords, guitartuna, lacuerda

FIXTURES = Path(__file__).parent / "fixtures" / "fonts"


def _html(nom: str) -> str:
    return (FIXTURES / nom).read_text(encoding="utf-8")


def _comprova_basic(tab, titol: str, artista: str, min_sec: int = 1, min_ch: int = 10) -> list[str]:
    assert tab is not None
    assert tab.titol == titol
    assert tab.artista == artista
    linies = tab.content.split("\n")
    assert all(l.strip() for l in linies), "sense línies en blanc"
    assert tab.content.count("<sec>") >= min_sec
    assert tab.content.count("<ch>") >= min_ch
    assert "|---" not in tab.content
    return linies


@pytest.fixture
def xarxa(monkeypatch):
    """`http.obte` amb respostes fixes: {prefix d'URL: html}; la resta, None (com un 404)."""
    respostes: dict[str, str] = {}
    demanades: list[str] = []

    def obte(url, params=None):
        demanades.append(url)
        return next((h for pre, h in respostes.items() if url.startswith(pre)), None)

    monkeypatch.setattr(http, "obte", obte)
    return respostes, demanades


# ── LaCuerda ────────────────────────────────────────────────────────────────────────────────────

URL_LC = "https://acordes.lacuerda.net/jarabe_de_palo/la_flaca-5.shtml"


def test_lacuerda_parseja():
    tab = lacuerda.parseja(_html("lacuerda.html"), URL_LC)
    linies = _comprova_basic(tab, "la Flaca", "Jarabe de Palo")
    assert tab.versio == 5 and tab.capo == 0
    assert linies[0] == "<sec>Intro</sec>"
    assert linies[1] == "<ch>Am</ch>  <ch>E7</ch>  <ch>D</ch>  <ch>F</ch>  <ch>G</ch>"
    assert linies[2] == "<ch>Am</ch>En la vida cono<ch>E7</ch>cí,"
    assert "<sec>CORO</sec>" in linies
    assert "aunque solo uno fue<ch>F</ch>ra<ch>F#</ch>,  <ch>G</ch>" in linies


def test_lacuerda_resultats_cerca():
    # En aquesta pàgina lOpen fa servir hds[NMAX-n] i fns[NMAX-n]: els arrays van al revés
    resultats = lacuerda.resultats_cerca(_html("lacuerda-cerca.html"))
    primer = resultats[0]
    assert (primer["hd"], primer["fn"], primer["titol"], primer["artista"]) == \
        ("luis_fonsi", "despacito", "Despacito", "Luis Fonsi")
    assert primer["versions"] == [(1, "R"), (2, "T"), (3, "R"), (4, "T"), (5, "T")]
    assert (resultats[1]["fn"], resultats[1]["titol"]) == ("me_ire", "Me iré")


def test_lacuerda_cerca(xarxa):
    respostes, _ = xarxa
    respostes[lacuerda.URL_CERCA] = _html("lacuerda-cerca.html")
    # Sense la pàgina de la cançó, les versions R surten de l'atribut lcd
    cs = lacuerda.cerca("Despacito", "Luis Fonsi", "es")
    assert [c.url for c in cs] == ["https://acordes.lacuerda.net/luis_fonsi/despacito.shtml",
                                   "https://acordes.lacuerda.net/luis_fonsi/despacito-3.shtml"]
    assert [c.versio for c in cs] == [1, 3]


def test_lacuerda_versions_index():
    html = """<div id=r_head><H1>la Flaca <br><A href="./">Jarabe de Palo</A></H1></div>
    <div id='rThumbs' class='rThumbs'><ul>
    <li id='liElm3'><div class='rtHead'><div class='tipoIcon tiR'></div><div class='rtLabel'>
      <a href='la_flaca-3.shtml'>Letra y Acordes</a></div></div></li>
    <li id='liElm2'><div class='rtHead'><div class='tipoIcon tiT'></div><div class='rtLabel'>
      <a href='la_flaca-2.shtml'>Tablatura</a></div></div></li>
    <li id='liElm1'><div class='rtHead'><div class='tipoIcon tiR'></div><div class='rtLabel'>
      <a href='la_flaca.shtml'>Letra y Acordes</a></div></div></li></ul></div>"""
    url = "https://acordes.lacuerda.net/jarabe_de_palo/la_flaca"
    assert lacuerda.versions_index(html, url) == [
        (3, "https://acordes.lacuerda.net/jarabe_de_palo/la_flaca-3.shtml"),
        (1, "https://acordes.lacuerda.net/jarabe_de_palo/la_flaca.shtml")]
    assert lacuerda._titol_index(html).strip() == "la Flaca"


# ── Acords Català ───────────────────────────────────────────────────────────────────────────────

URL_AC = "https://www.acordscatala.cat/ca/sau/boig-per-tu"


def test_acordscatala_parseja():
    tab = acordscatala.parseja(_html("acordscatala.html"), URL_AC)
    linies = _comprova_basic(tab, "Boig per tu", "Sau")
    assert linies[0] == "<sec>Estrofa 1</sec>"
    assert linies[1] == "Intro: <ch>FA</ch>   <ch>SIb</ch>    x4"
    assert linies[2] == "<ch>FA</ch> En la terra hu<ch>SIb</ch>mida escric"
    i = linies.index("<sec>Tornada</sec>")
    assert linies[i + 1] == "<ch>DO</ch> Se molt bé que des d´<ch>REm</ch>aquest bar"
    assert "<sec>Estrofa 2</sec>" in linies
    assert "      <ch>SOLm</ch> <ch>SIb</ch> <ch>MIb→SIb→DO</ch>" in linies  # acords en solfeig, tal com són


def test_acordscatala_cancons_artista():
    nom, cancons = acordscatala.cancons_artista(_html("acordscatala-cerca.html"), "https://www.acordscatala.cat/ca/sau")
    assert nom == "Sau"
    assert ("Boig per tu", URL_AC) in cancons
    assert ("Corre, corre't, corre", "https://www.acordscatala.cat/ca/sau/corre-corret-corre") in cancons


def test_acordscatala_cerca(xarxa):
    respostes, demanades = xarxa
    respostes["https://www.acordscatala.cat/ca/sau"] = _html("acordscatala-cerca.html")
    cs = acordscatala.cerca("Boig per tu", "Sau", "ca")
    assert [(c.url, c.titol, c.artista) for c in cs] == [(URL_AC, "Boig per tu", "Sau")]
    demanades.clear()
    assert acordscatala.cerca("Boig per tu", "Sau", "es") == [] and demanades == []


# ── GuitarTuna ──────────────────────────────────────────────────────────────────────────────────

URL_GT = "https://guitartuna.com/chords/wonderwall-oasis-original-guitar-chords-60b5c03ca597073ccc5707ab"
URL_ARTISTA_GT = "https://guitartuna.com/artists/oasis-easy-original-guitar-chords-tabs-6176da01e1a40179d11c472a"


def test_guitartuna_parseja():
    tab = guitartuna.parseja(_html("guitartuna.html"), URL_GT)
    linies = _comprova_basic(tab, "Wonderwall", "Oasis")
    assert (tab.capo, tab.to, tab.versio) == (2, "F#m", 1)
    assert linies[0] == "<sec>Intro 1</sec>"
    assert linies[1] == "<ch>Em7</ch>   <ch>G</ch>  <ch>Dsus4</ch>    <ch>A7sus4</ch>"
    assert "<ch>Em7</ch>Today is <ch>G</ch>gonna be the day" in linies
    assert "Rea<ch>Dsus4</ch>lized what you gotta do <ch>A7sus4</ch>" in linies
    assert "<sec>Pre-chorus 1</sec>" in linies


def test_guitartuna_cerca(xarxa):
    respostes, _ = xarxa
    respostes["https://guitartuna.com/artists/browse/o"] = (
        '<a href="/artists/oasis-ministry-easy-original-guitar-chords-tabs-66e1f713f7abd9b95a896cfa">Oasis Ministry</a>'
        f'<a href="{URL_ARTISTA_GT.removeprefix("https://guitartuna.com")}">Oasis</a>')
    respostes[URL_ARTISTA_GT] = _html("guitartuna-cerca.html")
    cs = guitartuna.cerca("Wonderwall", "Oasis", None)
    assert [c.url for c in cs] == [URL_GT, URL_GT.replace("-original-", "-easy-")]
    assert [(c.titol, c.artista, c.versio) for c in cs] == [("Wonderwall", "Oasis", 1), ("Wonderwall", "Oasis", 2)]
    assert guitartuna.url_browse("The Beatles") == "https://guitartuna.com/artists/browse/b"


# ── Cifra Club ──────────────────────────────────────────────────────────────────────────────────
# cifraclub.html és la pàgina real (baixada amb el navegador) reduïda al títol, el to, el capo i el
# <pre>. CIFRACLUB és l'estructura antiga, la que documenta src/lib/importers/cifraclub.ts.

URL_CC = "https://www.cifraclub.com.br/oasis/wonderwall/"


def test_cifraclub_parseja_pagina_real():
    tab = cifraclub.parseja(_html("cifraclub.html"), URL_CC)
    linies = _comprova_basic(tab, "Wonderwall", "Oasis", min_sec=5)
    assert (tab.capo, tab.to) == (2, "F#m")
    assert linies[:2] == ["<sec>Intro</sec>", "<ch>Em7</ch>  <ch>G</ch>  <ch>D4</ch>  <ch>A7(4)</ch>"]
    assert "<ch>Em7</ch>    Today is g<ch>G</ch>onna be the day" in linies
    assert "<sec>Refrão</sec>" in linies
    # Sense espais de mida zero, fletxes de rasgueig ni "Parte 2 de 3"
    assert not any(c in tab.content for c in ("​", "↓", "Parte "))


def test_cifraclub_cerca(xarxa):
    respostes, demanades = xarxa
    respostes[cifraclub.URL_CERCA] = _html("cifraclub-cerca.json")
    cs = cifraclub.cerca("Wonderwall", "Oasis", None)
    assert [(c.url, c.titol, c.artista) for c in cs] == [(URL_CC, "Wonderwall", "Oasis")]
    assert demanades == [cifraclub.URL_CERCA]
    assert cifraclub.baixa(cs[0]) is None  # sense navegador, la pàgina (Akamai) no es pot baixar


CIFRACLUB ="""<html lang="pt-BR"><head><title>Wonderwall - Oasis - Cifra Club</title></head><body>
<h1 class="t1">Wonderwall</h1><h2 class="t3"><a href="/oasis/">Oasis</a></h2>
<span id="cifra_tom">tom: <a>Em</a></span> <span id="cifra_capo">capotraste na <a>2ª casa</a></span>
<div class="cifra_cnt"><pre>[Intro] <b>Em7</b>  <b>G</b>  <b>Dsus4</b>  <b>A7(4)</b>

[Primeira Parte]

<b>Em7</b>      <b>G</b>
Today is gonna be the day
         <b>Dsus4</b>                    <b>A7(4)</b>
That they're gonna throw it back to you

[Refrão]

<b>C9</b>          <b>D</b>       <b>Em7</b>
And all the roads we have to walk are winding
<b>C9</b>          <b>D</b>       <b>Em7</b>   (2x)
<span class="tablatura"><span class="cnt">E|-----3---3---|
B|---3---3-----|</span></span>
</pre></div></body></html>"""


def test_cifraclub_parseja():
    tab = cifraclub.parseja(CIFRACLUB, "https://www.cifraclub.com.br/oasis/wonderwall/")
    linies = _comprova_basic(tab, "Wonderwall", "Oasis")
    assert (tab.capo, tab.to) == (2, "Em")
    assert linies[:3] == ["<sec>Intro</sec>", "<ch>Em7</ch>  <ch>G</ch>  <ch>Dsus4</ch>  <ch>A7(4)</ch>",
                          "<sec>Primeira Parte</sec>"]
    assert linies[3] == "<ch>Em7</ch>Today is <ch>G</ch>gonna be the day"
    assert "<sec>Refrão</sec>" in linies
    # Acords amb text ("(2x)"): com una línia de lletra, l'acord no ocupa amplada i hi queden els espais
    assert linies[-1] == "<ch>C9</ch>            <ch>D</ch>        <ch>Em7</ch>      (2x)"


# ── AcordesWeb ──────────────────────────────────────────────────────────────────────────────────

URL_AW = "https://acordesweb.com/cancion/cesk-freixas/la-petita-rambla-del-poble-sec"


def test_acordesweb_parseja():
    tab = acordesweb.parseja(_html("acordesweb.html"), URL_AW)
    linies = _comprova_basic(tab, "La petita rambla del poble sec", "Cesk Freixas", min_sec=0)
    # Els espais no separables de la web passen a ser espais normals
    assert linies[0] == "ass<ch>G</ch>egut a la Plaça del S<ch>B7</ch>urtidor"
    assert "\xa0" not in tab.content


def test_acordesweb_cerca(xarxa):
    respostes, demanades = xarxa
    respostes[acordesweb.URL_CERCA] = _html("acordesweb-cerca.html")
    cs = acordesweb.cerca("La petita rambla del Poble Sec", "Cesk Freixas", "ca")
    assert [(c.url, c.titol, c.artista) for c in cs] == [(URL_AW, "La petita rambla del poble sec", "Cesk Freixas")]
    demanades.clear()
    assert acordesweb.cerca("Wonderwall", "Oasis", "en") == []
    assert len(demanades) == 2  # títol i artista, i després només el títol


# ── E-Chords ────────────────────────────────────────────────────────────────────────────────────

URL_EC = "https://www.e-chords.com/es/acordes/oasis/wonderwall"


def test_echords_parseja():
    tab = echords.parseja(_html("echords.html"), URL_EC)
    linies = _comprova_basic(tab, "Wonderwall", "Oasis")
    assert tab.capo == 2
    # Sense l'alternativa "(Simplified: Em G D A)"
    assert linies[:3] == ["<sec>Intro</sec>", "<ch>Em7</ch>    <ch>G</ch>  <ch>D4</ch>   <ch>A7(4)</ch>      (4x)",
                          "<ch>Em7</ch>Today is <ch>G</ch>gonna be the day"]
    assert "Simplified" not in tab.content


def test_echords_cerca(xarxa):
    respostes, demanades = xarxa
    respostes["https://www.e-chords.com/oasis"] = _html("echords-artista.html")
    cs = echords.cerca("Wonderwall", "Oasis", None)
    assert [(c.url, c.titol, c.versio) for c in cs] == [(URL_EC, "Wonderwall", 1),
                                                       (URL_EC + "-ver-2", "Wonderwall (ver. 2)", 2)]
    assert demanades == ["https://www.e-chords.com/oasis"]
    assert echords.urls_artista("The Beatles") == ["https://www.e-chords.com/the-beatles",
                                                   "https://www.e-chords.com/beatles"]
    assert echords.baixa(cs[0]) is None  # sense navegador (Cloudflare) no es baixa res
