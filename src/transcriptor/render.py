"""Render: elements + seccions → `content` amb el format exacte de la BD del canconer.

- `<sec>Nom</sec>` en una línia pròpia.
- `<ch>X</ch>` dins la línia de lletra, just abans de la lletra on canvia l'acord.
- Zones instrumentals amb els compassos marcats: "|" al primer temps de cada compàs i "'" a la resta,
  amb l'acord damunt del temps on comença (`<ch>` és d'amplada zero i es pinta per sobre del text):
    A               C#m     Bm
    |   '   '   '   |   '   |   '
  Sense barra de tancament: si la veu entra a mig compàs, la línia acaba al temps on entra.
  Sense pulsacions, línies només d'acords amb 4 espais entre acords (com `ensureChordSpacing`).
- Sense línies buides (com `collapseBlankLines` del canconer).
"""

from __future__ import annotations

from .notation import transposa

ACORDS_PER_LINIA = 8
ESPAI_ACORDS = "    "
PULSACIONS_PER_LINIA = 16  # 4 compassos de 4/4
ESPAI_TEMPS = "   "  # cada temps (marca + espais) fa ~1 em amb la font del cançoner


def _amplada(etiqueta: str) -> int:
    """Amplada aproximada d'un acord (en negreta i per sobre del text), en espais de la lletra."""
    return 2 * len(etiqueta) + 2


def linia_amb_acords(text: str, acords: list[list]) -> str:
    """Insereix `<ch>` a les posicions de caràcter. Les posicions més enllà del text van al final."""
    # "<" i ">" dins la lletra trencarien el format de la BD (parse de model.ts del canconer)
    text = text.replace("<", "‹").replace(">", "›")
    sortida, cursor = [], 0
    for pos, etiqueta, *_ in sorted(acords, key=lambda a: a[0]):
        if pos > len(text):
            # Acord després del final de la lletra: separat per un espai
            sortida.append(text[cursor:])
            cursor = len(text)
            if not sortida[-1].endswith(" ") and "".join(sortida):
                sortida.append(" ")
            sortida.append(f"<ch>{etiqueta}</ch>")
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


def linies_compassos(pulsacions: list[list]) -> list[str]:
    """Línies amb els compassos d'una zona instrumental (pulsacions: [t, temps, etiqueta o None])."""
    compassos: list[list[tuple[int, str | None]]] = []
    for _, temps, etiqueta in pulsacions:
        if temps == 1 or not compassos:
            compassos.append([])
        compassos[-1].append((temps, etiqueta))
    per_compas = max(len(c) for c in compassos)
    per_linia = max(1, PULSACIONS_PER_LINIA // per_compas)
    linies = []
    for i in range(0, len(compassos), per_linia):
        sortida, ocupat = [], 0  # ocupat: espais que encara tapa l'últim acord
        for compas in compassos[i : i + per_linia]:
            for temps, etiqueta in compas:
                marca = "|" if temps == 1 else "'"
                if etiqueta:
                    if ocupat > 0:  # dos canvis seguits: es separa el segon perquè no es trepitgin
                        sortida.append(" " * ocupat)
                    sortida.append(f"<ch>{etiqueta}</ch>")
                    ocupat = _amplada(etiqueta)
                sortida.append(marca + ESPAI_TEMPS)
                ocupat -= 1 + len(ESPAI_TEMPS)
        linies.append("".join(sortida).rstrip())
    return linies


def content(elements: list[dict], seccions: list[dict], capo: int = 0) -> str:
    """`capo` > 0: els acords s'escriuen transposats a les formes (com fa la BD amb cejilla)."""

    def et(a: str) -> str:
        return transposa(a, -capo) if capo else a

    linies: list[str] = []
    for s in seccions:
        linies.append(f"<sec>{s['name']}</sec>")
        for i in s["elements"]:
            e = elements[i]
            if e["tipus"] == "linia":
                linies.append(linia_amb_acords(e["text"], [[p, et(a), *r] for p, a, *r in e["acords"]]))
            elif e.get("pulsacions"):
                linies.extend(linies_compassos([[t, temps, et(a) if a else None]
                                                for t, temps, a in e["pulsacions"]]))
            else:
                linies.extend(linies_acords([et(a) for a, _ in e["acords"]]))
    return "\n".join(l for l in linies if l.strip())
