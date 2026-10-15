"""Render: elements + seccions → `content` amb el format exacte de la BD del canconer.

- `<sec>Nom</sec>` en una línia pròpia.
- `<ch>X</ch>` dins la línia de lletra, just abans de la lletra on canvia l'acord.
- Línies només d'acords amb 4 espais entre acords (com `ensureChordSpacing` del canconer).
- Sense línies buides (com `collapseBlankLines` del canconer).
"""

from __future__ import annotations

from .notation import transposa

ACORDS_PER_LINIA = 8
ESPAI_ACORDS = "    "


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
            else:
                linies.extend(linies_acords([et(a) for a, _ in e["acords"]]))
    return "\n".join(l for l in linies if l.strip())
