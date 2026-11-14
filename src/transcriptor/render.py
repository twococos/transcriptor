"""Render: elements + seccions → `content` amb el format exacte de la BD del canconer.

- `<sec>Nom</sec>` en una línia pròpia.
- `<ch>X</ch>` dins la línia de lletra, just abans de la lletra on canvia l'acord.
- Zones instrumentals amb els compassos marcats: "|" al primer temps de cada compàs i "'" a la resta,
  amb l'acord damunt del temps on comença (`<ch>` és d'amplada zero i es pinta per sobre del text):
    A       C#m Bm
    | ' ' ' | ' | '
  Cada línia comença amb l'acord que sona, encara que vingui de la línia anterior. Sense barra de
  tancament: si la veu entra a mig compàs, la línia acaba al temps on entra. L'espai de cada temps
  és el mínim perquè els acords de la zona no es trepitgin (de 2 a 4 caràcters).
  Les rodes que es repeteixen (postprocess/rodes.py) s'escriuen una vegada, començant línia, amb
  "(x3)" al final. Si la roda ocupa dues línies, "x3" va sol a sota (repeteix des de l'inici de la
  secció o de la marca anterior); si abans hi ha alguna altra cosa, s'escriu sencera.
  Sense pulsacions, línies només d'acords amb 4 espais entre acords (com `ensureChordSpacing`).
- Sense línies buides (com `collapseBlankLines` del canconer).
"""

from __future__ import annotations

import math
import re

from .notation import transposa
from .postprocess import rodes

ACORDS_PER_LINIA = 8
ESPAI_ACORDS = "    "
PULSACIONS_PER_LINIA = 16  # 4 compassos de 4/4
AMPLADA_TEMPS = (2, 4)  # caràcters per temps (marca + espais): mínim i màxim
_RE_MARCA_SOLA = re.compile(r"x\d+")


def _amplada(etiqueta: str) -> int:
    """Amplada aproximada d'un acord (en negreta i per sobre del text), en espais de la lletra."""
    return 2 * len(etiqueta) + 2


def linia_amb_acords(text: str, acords: list[list]) -> str:
    """Insereix `<ch>` a les posicions de caràcter. Les posicions més enllà del text van al final."""
    # "<" i ">" dins la lletra trencarien el format de la BD (parse de model.ts del canconer)
    text = text.replace("<", "‹").replace(">", "›")
    sortida, cursor, darrer = [], 0, None
    for pos, etiqueta, *_ in sorted(acords, key=lambda a: a[0]):
        if pos > len(text):
            # Acord després del final de la lletra: separat per un espai, o per l'amplada de l'acord
            # anterior si també és després de la lletra (perquè no es trepitgin)
            sortida.append(text[cursor:])
            cursor = len(text)
            if darrer:
                sortida.append(" " * _amplada(darrer))
            elif not sortida[-1].endswith(" ") and "".join(sortida):
                sortida.append(" ")
            sortida.append(f"<ch>{etiqueta}</ch>")
            darrer = etiqueta
            continue
        sortida.append(text[cursor:pos])
        sortida.append(f"<ch>{etiqueta}</ch>")
        cursor = pos
    sortida.append(text[cursor:])
    return "".join(sortida).rstrip()


def linies_acords(acords: list[str]) -> list[str]:
    """Línies només d'acords (col·lapsant repeticions consecutives)."""
    seq = [a for i, a in enumerate(acords) if i == 0 or a != acords[i - 1]]
    return [ESPAI_ACORDS.join(f"<ch>{a}</ch>" for a in seq[i : i + ACORDS_PER_LINIA])
            for i in range(0, len(seq), ACORDS_PER_LINIA)]


def _linies_de_trossos(pulsacions: list[list], inici_bloc: bool) -> list[tuple[list, str]]:
    """Línies (temps [(temps, etiqueta o None)], marca final) d'una zona, amb les rodes plegades."""
    per_compas = max(len(c) for c in rodes.compassos(pulsacions))
    per_linia = max(1, PULSACIONS_PER_LINIA // per_compas)
    linies: list[tuple[list, str]] = []

    def afegeix(compassos: list, sonant: str | None, mida: int, marca: str = "") -> str | None:
        for i in range(0, len(compassos), mida):
            temps = [(p[1], p[2]) for c in compassos[i:i + mida] for p in c]
            if temps and not temps[0][1] and sonant:
                temps[0] = (temps[0][0], sonant)  # la línia comença amb l'acord que sona
            for _, et in temps:
                sonant = et or sonant
            linies.append((temps, ""))
        if marca and linies:
            linies[-1] = (linies[-1][0], marca)
        return sonant

    net = inici_bloc  # res escrit des de l'inici de la secció o de l'última marca sola
    for tros in rodes.trossos(pulsacions):
        P = len(tros.compassos)
        n = math.ceil(P / per_linia)
        if tros.vegades == 1:
            afegeix(tros.compassos, tros.sonant, per_linia)
        elif n == 1:
            afegeix(tros.compassos, tros.sonant, per_linia, f"(x{tros.vegades})")
        elif net:
            afegeix(tros.compassos, tros.sonant, math.ceil(P / n))
            linies.append(([], f"x{tros.vegades}"))
            net = True
            continue
        else:
            sonant = tros.sonant
            for r in range(tros.vegades):
                sonant = afegeix(tros.originals[r * P:(r + 1) * P], sonant, math.ceil(P / n))
        net = False
    return linies


def _amplada_temps(linies: list[tuple[list, str]]) -> int:
    """Caràcters per temps perquè cap acord no tapi el següent de la mateixa línia."""
    cal = AMPLADA_TEMPS[0]
    for temps, _ in linies:
        amb = [(k, et) for k, (_, et) in enumerate(temps) if et]
        for (k, et), (k2, _) in zip(amb, amb[1:]):
            cal = max(cal, math.ceil(_amplada(et) / (k2 - k)))
    return min(cal, AMPLADA_TEMPS[1])


def linies_compassos(pulsacions: list[list], inici_bloc: bool = False) -> list[str]:
    """Línies amb els compassos d'una zona instrumental (pulsacions: [t, temps, etiqueta o None]).
    `inici_bloc`: no hi ha res escrit abans a la secció (una marca "x3" sola hi pot anar)."""
    linies = _linies_de_trossos(pulsacions, inici_bloc)
    w = _amplada_temps(linies)
    sortida = []
    for temps, marca in linies:
        trossos, ocupat = [], 0  # ocupat: espais que encara tapa l'últim acord
        for t, etiqueta in temps:
            if etiqueta:
                if ocupat > 0:  # dos canvis massa junts: es separa el segon perquè no es trepitgin
                    trossos.append(" " * ocupat)
                trossos.append(f"<ch>{etiqueta}</ch>")
                ocupat = _amplada(etiqueta)
            trossos.append(("|" if t == 1 else "'") + " " * (w - 1))
            ocupat -= w
        linia = "".join(trossos).rstrip()
        sortida.append(f"{linia}  {marca}" if linia and marca else linia or marca)
    return sortida


def _zones(elements: list[dict], idx: list[int]) -> list[dict]:
    """Els elements d'una secció, amb les zones instrumentals seguides unides en una."""
    sortida: list[dict] = []
    for i in idx:
        e = elements[i]
        ant = sortida[-1] if sortida else None
        if (e["tipus"] == "instrumental" and e.get("pulsacions") and ant and ant["tipus"] == "instrumental"
                and ant.get("pulsacions")):
            vistes = {p[0] for p in ant["pulsacions"]}
            puls = sorted(ant["pulsacions"] + [p for p in e["pulsacions"] if p[0] not in vistes], key=lambda p: p[0])
            sortida[-1] = {**ant, "end": e["end"], "acords": ant["acords"] + e["acords"], "pulsacions": puls}
        else:
            sortida.append(e)
    return sortida


def content(elements: list[dict], seccions: list[dict], capo: int = 0) -> str:
    """`capo` > 0: els acords s'escriuen transposats a les formes (com fa la BD amb cejilla)."""

    def et(a: str) -> str:
        return transposa(a, -capo) if capo else a

    linies: list[str] = []
    for s in seccions:
        linies.append(f"<sec>{s['name']}</sec>")
        net = True  # res escrit des del títol o des de l'última marca sola ("x3")
        for e in _zones(elements, s["elements"]):
            if e["tipus"] == "linia":
                linies.append(linia_amb_acords(e["text"], [[p, et(a), *r] for p, a, *r in e["acords"]]))
                net = False
            elif e.get("pulsacions"):
                noves = linies_compassos([[t, temps, et(a) if a else None] for t, temps, a in e["pulsacions"]], net)
                linies.extend(noves)
                net = bool(noves) and bool(_RE_MARCA_SOLA.fullmatch(noves[-1]))
            else:
                linies.extend(linies_acords([et(a) for a, _ in e["acords"]]))
                net = False
    return "\n".join(l for l in linies if l.strip())
