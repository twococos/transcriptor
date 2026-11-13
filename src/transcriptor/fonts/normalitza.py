"""Tabs al format del projecte: acords, seccions i repeticions.

1. Acords (`acord`): solfeig (Do, SOL#m, Lam) → anglès, bemolls → sostinguts, sinònims de sufix
   (min, -, M7, 7M, Δ, º, ø, +, (9)…) → la grafia del projecte, i baix ("G/B"). Cada acord es desa
   de dues maneres: `escrit` (el que es mostrarà) i `classe` (l'etiqueta del vocabulari de BTC a
   nivell sevenths, per comparar amb l'àudio).
2. Seccions (`seccio`): diccionari de sinònims de src/lib/importers/normalizeSections.ts del
   canconer (+ portuguès) → structure.SECTION_TYPES.
3. Repeticions (`tab`): "x2"/"bis" sol repeteix el bloc anterior, "(x2)" al final repeteix la
   línia, una línia d'acords amb "x4" es repeteix, una secció citada sense contingut ("[Chorus]")
   copia l'última amb el mateix nom, i les estrofes sense cap acord hereten els de l'estrofa
   anterior (marcades `heretada`: les tabs ho fan sovint i no sempre és cert).
"""

from __future__ import annotations

import re
import unicodedata

from ..notation import NOTES, nota, transposa
from ..structure import SECTION_TYPES
from .model import AcordTab, LiniaTab, SeccioTab, Tab, TabCrua

_SOLFEIG = {"do": "C", "re": "D", "mi": "E", "fa": "F", "sol": "G", "la": "A", "si": "B"}
_RE_ARREL = re.compile(r"^(sol|do|re|mi|fa|la|si|[A-G])([#♯b♭]?)", re.I)

# Sufix (ja net) → (grafia del projecte, classe de BTC a nivell sevenths). L'ordre importa: primer
# els més llargs. La classe és la del vocabulari de chords_clean (sus, add9, 6 i aug → major).
_SUFIXOS: list[tuple[str, str, str]] = [
    (r"m7b5|min7b5|-7b5|ø7?|m7\(b5\)|m7\(5-\)|m7-5", "m7b5", "m7b5"),
    (r"dim7|º7|°7|o7", "dim7", "dim"),
    (r"dim|º|°", "dim", "dim"),
    (r"m\(?maj7\)?|mM7|m7M|m\(7M\)|-maj7", "mmaj7", "m"),
    (r"maj9|M9|7M\(9\)|Δ9", "maj9", "maj7"),
    (r"maj7|M7|7M|Δ7?|ma7|maj|7\+", "maj7", "maj7"),
    (r"m6|min6|-6", "m6", "m"),
    (r"m9|min9|-9|m7\(9\)", "m9", "m7"),
    (r"m11|m7\(11\)", "m11", "m7"),
    (r"m7|min7|-7", "m7", "m7"),
    (r"m\(?add9\)?|madd9|m\(9\)|m2", "madd9", "m"),
    (r"m|min|-", "m", "m"),
    (r"7sus4|7sus|7\(4\)|7/4|9sus4|9sus", "7sus4", "7"),
    (r"sus4|sus|\(4\)|4", "sus4", ""),
    (r"sus2|\(2\)", "sus2", ""),
    (r"add9|add2|\(add9\)|\(9\)|2", "add9", ""),
    (r"6/9|69|6\(9\)", "6", ""),
    (r"6", "6", ""),
    (r"7\(9\)|9", "9", "7"),
    (r"7\(13\)|13", "13", "7"),
    (r"7\(11\)|11", "11", "7"),
    (r"7\(b9\)|7b9|7\(#9\)|7#9|7\(#5\)|7#5|7\(b5\)|7b5|7", "7", "7"),
    (r"aug|\+5?|\(#5\)", "aug", ""),
    (r"5", "5", ""),
    (r"M|", "", ""),
]
_RE_SUFIXOS = [(re.compile(f"^(?:{p})$"), e, c) for p, e, c in _SUFIXOS]


def _arrel(text: str) -> tuple[str, str] | None:
    """(nota amb sostinguts, resta) o None. El solfeig es reconeix en qualsevol caixa."""
    m = _RE_ARREL.match(text)
    if not m:
        return None
    base = m.group(1)
    if len(base) > 1:
        base = _SOLFEIG[base.lower()]
    elif base.islower():
        return None  # "a", "e" soles són paraules
    alteracio = {"♯": "#", "♭": "b"}.get(m.group(2), m.group(2))
    return nota(base.upper() + alteracio), text[m.end():]


def acord(text: str) -> AcordTab | None:
    """Acord escrit en una tab → AcordTab (amb col=0), o None si no és un acord."""
    t = text.strip().strip("*").replace(" ", "")
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1]
    if not t or t.upper().replace(".", "") in ("NC", "N", "X"):
        return None
    r = _arrel(t)
    if r is None:
        return None
    arrel, resta = r
    baix = None
    if "/" in resta and not resta.startswith("6/9") and not re.search(r"7/4$", resta):
        resta, _, b = resta.rpartition("/")
        rb = _arrel(b)
        if rb is None or rb[1]:
            return None
        baix = rb[0]
    for patro, escrit, classe in _RE_SUFIXOS:
        if patro.match(resta):
            break
    else:
        # Sufix desconegut: el reduïm a la qualitat bàsica que se'n pot deduir
        if not re.match(r"^[\w()#+\-º°øΔ/]*$", resta):
            return None
        menor = bool(re.match(r"^(m(?!aj)|min|-)", resta))
        escrit, classe = ("m", "m") if menor else ("", "")
    escrit_complet = arrel + escrit + (f"/{baix}" if baix and baix != arrel else "")
    return AcordTab(col=0, escrit=escrit_complet, classe=arrel + classe)


def transposa_acord(a: AcordTab, semitons: int) -> AcordTab:
    return AcordTab(col=a.col, escrit=transposa(a.escrit, semitons), classe=transposa(a.classe, semitons))


# Seccions
_SINONIMS = {
    "Estrofa": "estrofa estrofes estrofas verso versos verse verses primeiraparte segundaparte "
               "terceiraparte quartaparte parte",
    "Tornada": "tornada tornades estribillo estribillos coro coros chorus refrain refrains hook refrao "
               "postchorus postcoro",
    "Pre-tornada": "pretornada preestribillo precoro prechorus prehook prerefrao",
    "Pont": "pont puente bridge middle8 ponte",
    "Solo": "solo solos guitarsolo solodeguitarra solodeguitar solodebajo basssolo solodepiano pianosolo",
    "Instrumental": "instrumental instrumentals riff",
    "Interludi": "interludi interludio interlude break breakdown",
    "Intro": "intro introduccio introduccion introduction introducao fadein",
    "Outro": "outro final finalitzacio conclusio cloenda cierre conclusion ending end coda fadeout fade "
             "finale tag",
}
_TIPUS_DE = {s: t for t, ss in _SINONIMS.items() for s in ss.split()}
assert set(_SINONIMS) <= set(SECTION_TYPES)


def _clau(nom: str) -> str:
    nom = unicodedata.normalize("NFD", nom.lower())
    nom = "".join(c for c in nom if not unicodedata.combining(c))
    nom = re.sub(r"\s*[\(\[]?\s*(x\s*\d+|\d+\s*x|bis)\s*[\)\]]?\s*:?$", "", nom.strip())  # "Tornada x2"
    nom = re.sub(r"\b([ivx]+|\d+)\b\W*$", "", nom.strip())  # "Verse 2", "Estrofa II"
    return re.sub(r"[^a-z0-9]", "", nom).rstrip("0123456789")


def seccio(nom: str) -> SeccioTab:
    clau = _clau(nom)
    tipus = _TIPUS_DE.get(clau)
    if tipus is None:
        tipus = next((t for s, t in _TIPUS_DE.items() if len(s) >= 4 and clau.startswith(s)), None)
    return SeccioTab(nom=nom.strip(), tipus=tipus)


# Lectura del content i repeticions
_RE_SEC = re.compile(r"^\s*<sec>([^<]*)</sec>\s*$")
_RE_CH = re.compile(r"<ch>([^<]*)</ch>")
_RE_REPETICIO_SOLA = re.compile(r"^[\(\[]?\s*(?:x\s*(\d+)|(\d+)\s*x|(bis))\s*[\)\]]?:?$", re.I)
_RE_REPETICIO_FINAL = re.compile(r"\s*[\(\[]?\s*(?:x\s*(\d+)|(\d+)\s*x|(bis))\s*[\)\]]?\s*$", re.I)
MAX_REPETICIONS = 8


def _vegades(m: re.Match) -> int:
    return max(1, min(MAX_REPETICIONS, 2 if m.group(3) else int(m.group(1) or m.group(2))))


def _llegeix_linia(linia: str) -> tuple[str, list[AcordTab]]:
    text, acords = "", []
    for tros in re.split(r"(<ch>[^<]*</ch>)", linia):
        m = _RE_CH.fullmatch(tros)
        if m:
            a = acord(m.group(1))
            if a is not None:
                a.col = len(text)
                acords.append(a)
        else:
            text += tros
    return text.rstrip(), acords


def _copia(l: LiniaTab, seccio_idx: int | None, repeticio: int) -> LiniaTab:
    return LiniaTab(text=l.text, acords=[AcordTab(a.col, a.escrit, a.classe) for a in l.acords], seccio=seccio_idx,
                    repeticio=repeticio, heretada=l.heretada, origen=l.origen)


def tab(crua: TabCrua) -> Tab:
    """TabCrua → Tab desplegada (vegeu la capçalera). `transport` comença al capo de la pàgina."""
    seccions: list[SeccioTab] = []
    linies: list[LiniaTab] = []
    per_nom: dict[str, list[LiniaTab]] = {}  # última aparició de cada secció, per clau del nom
    inici_seccio = inici_bloc = 0
    actual: int | None = None

    def tanca_seccio() -> None:
        if actual is None:
            return
        propies = linies[inici_seccio:]
        s = seccions[actual]
        if not propies:
            # Secció citada sense contingut ("[Chorus]"): copia l'última amb aquest nom o tipus
            font = per_nom.get(_clau(s.nom))
            if font is None and s.tipus:
                font = next((v for v in reversed(per_nom.values()) if seccions[v[0].seccio].tipus == s.tipus), None)
            if font:
                linies.extend(_copia(l, actual, l.repeticio + 1) for l in font)
        else:
            per_nom[_clau(s.nom)] = propies

    for i, cru in enumerate(crua.content.replace("\r", "").split("\n")):
        m = _RE_SEC.match(cru)
        if m:
            tanca_seccio()
            nom = m.group(1)
            mr = _RE_REPETICIO_FINAL.search(nom)
            seccions.append(seccio(nom[: mr.start()] if mr and mr.start() > 0 else nom))
            actual = len(seccions) - 1
            inici_seccio = inici_bloc = len(linies)
            continue
        text, acords = _llegeix_linia(cru)
        net = text.strip()
        if not net and not acords:
            continue
        if not acords:
            mr = _RE_REPETICIO_SOLA.match(net)
            if mr:
                bloc = linies[inici_bloc:]
                for k in range(_vegades(mr) - 1):
                    linies.extend(_copia(l, l.seccio, l.repeticio + k + 1) for l in bloc)
                inici_bloc = len(linies)
                continue
        n = 1
        mr = _RE_REPETICIO_FINAL.search(text)
        if mr and (acords or mr.start() > 0):
            n = _vegades(mr)
            text = text[: mr.start()].rstrip()
        if not re.search(r"\w", text):
            text = ""
        if not text and not acords:
            continue
        l = LiniaTab(text=text, acords=acords, seccio=actual, origen=i)
        linies.append(l)
        linies.extend(_copia(l, actual, k) for k in range(1, n))
    tanca_seccio()
    _hereta(linies, seccions)
    return Tab(crua=crua, linies=linies, seccions=seccions, transport=crua.capo)


def _hereta(linies: list[LiniaTab], seccions: list[SeccioTab]) -> None:
    """Seccions amb lletra però sense cap acord: els de la mateixa línia de l'última secció del
    mateix tipus que en tenia (columna proporcional a la llargada de la línia)."""
    per_seccio: dict[int, list[LiniaTab]] = {}
    for l in linies:
        if l.seccio is not None:
            per_seccio.setdefault(l.seccio, []).append(l)
    darrera: dict[str, list[LiniaTab]] = {}
    for k, ls in sorted(per_seccio.items()):
        tipus = seccions[k].tipus
        if not tipus:
            continue
        if any(l.acords for l in ls):
            darrera[tipus] = ls
            continue
        model = [l for l in darrera.get(tipus, []) if l.text]
        if not model:
            continue
        for j, l in enumerate(x for x in ls if x.text):
            m = model[j % len(model)]
            escala = len(l.text) / max(len(m.text), 1)
            l.acords = [AcordTab(min(round(a.col * escala), len(l.text)), a.escrit, a.classe) for a in m.acords]
            l.heretada = True


def de_content(content: str, capo: int = 0, lloc: str = "bd") -> TabCrua:
    """El content d'una cançó del canconer (escrit per una persona) com a font."""
    return TabCrua(lloc=lloc, url="", titol="", artista="", content=content, capo=capo)


def classe_majmin(classe: str) -> tuple[int, bool] | None:
    """'F#m7' → (6, True): arrel i si és menor. Per comparar a nivell major/menor."""
    m = re.match(r"^([A-G]#?)(.*)$", classe)
    if not m:
        return None
    return NOTES.index(m.group(1)), m.group(2).startswith(("m", "dim")) and not m.group(2).startswith("maj")


def a_content(t: Tab, desplegat: bool = False) -> str:
    """Tab normalitzada → content del canconer (acords `escrit`, al to de les formes de la pàgina).
    Sense `desplegat`, només les línies originals (com està escrita la pàgina)."""
    sortida, seccio_ant = [], None
    for l in t.linies:
        if not desplegat and l.repeticio:
            continue
        if l.seccio is not None and l.seccio != seccio_ant:
            sortida.append(f"<sec>{t.seccions[l.seccio].nom}</sec>")
        seccio_ant = l.seccio
        text, cursor, linia = l.text, 0, ""
        for a in sorted(l.acords, key=lambda a: a.col):
            col = max(a.col, cursor)
            if col > len(text):
                text = text.ljust(col)
            linia += text[cursor:col] + f"<ch>{a.escrit}</ch>"
            cursor = col
        sortida.append((linia + text[cursor:]).rstrip())
    return "\n".join(sortida)
