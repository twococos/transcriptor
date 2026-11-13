"""Tab en text pla (acords a la línia de sobre de la lletra) → content del canconer.

El fan servir Ultimate Guitar (que marca els acords amb [ch]…[/ch]) i les tabs enganxades a mà.
Regles, com src/lib/importers/ultimateGuitar.ts del canconer:
- Una línia és d'acords si, sense els acords, només hi queden espais, barres de compàs, "x2"…
- Una línia d'acords seguida d'una de lletra s'hi fusiona: cada acord va a la seva columna.
- "[Nom]" o "Nom:" sol a la línia és una secció; la capçalera d'abans de la primera secció o
  línia d'acords (títol, afinació, capo…) es descarta, i també les tabs de punteig i els
  diagrames d'acords ("Em7  0-2-2-0-3-3").
"""

from __future__ import annotations

import re

RE_SECCIO = re.compile(r"^\s*\[([^\]\n]{1,40})\]\s*(.*)$")
RE_SECCIO_DOS_PUNTS = re.compile(
    r"^\s*((?:pre[- ]?)?(?:intro|verse|verso|estrofa|chorus|coro|estribillo|tornada|refr[aã]o|bridge|puente|pont|"
    r"solo|outro|final|interlude|interludio|instrumental|riff|ponte|primeira parte|segunda parte)\s*\d*)\s*:?\s*$",
    re.I)
RE_PUNTEIG = re.compile(r"^\s*[eBGDAEbgdae]?\s*\|[-0-9|hpbr/\~x()\s]{6,}$")
RE_DIAGRAMA = re.compile(r"^\s*\S+\s+(?:[x0-9]{1,2}[- ]?){6}\s*$")
RE_ACORD_PLA = re.compile(
    r"^\(?(?:[A-G][#b]?|(?:DO|RE|MI|FA|SOL|LA|SI|Do|Re|Mi|Fa|Sol|La|Si)[#b]?)"
    r"(?:m|maj|min|dim|aug|sus|add|M|º|°|ø|\+|-|\d|\(|\)|/|[#b])*(?:/[A-G][#b]?)?\)?$")
RE_SOBRANT = re.compile(r"^(?:[|:.\-–/\s]|x\s?\d+|\d+\s?x|\(x?\d+x?\)|bis|N\.?C\.?)*$", re.I)


def es_acord(token: str) -> bool:
    return bool(RE_ACORD_PLA.match(token)) and token.lower() not in ("a", "la", "mi", "si", "re", "do", "fa")


def acords_de_linia(linia: str) -> list[tuple[int, str]] | None:
    """Si la línia (text pla) és només d'acords, [(columna, acord)]; si no, None."""
    if not linia.strip():
        return None
    acords, resta = [], []
    for m in re.finditer(r"\S+", linia):
        t = m.group(0)
        if es_acord(t.strip("|")) and t.strip("|"):
            acords.append((m.start() + (len(t) - len(t.lstrip("|"))), t.strip("|")))
        else:
            resta.append(t)
    if not acords or not RE_SOBRANT.match(" ".join(resta)):
        return None
    # Les notes soles ("A", "Si", "La") també són paraules: cal que almenys un token sigui
    # inequívocament un acord o que la línia en tingui dos o més
    if len(acords) == 1 and acords[0][1] in ("A", "Do", "Re", "Mi", "Fa", "Sol", "La", "Si") and resta:
        return None
    return acords


def fusiona(acords: list[tuple[int, str]], lletra: str | None) -> str:
    """Línia de content: els acords inserits a la seva columna de la lletra (o sols)."""
    if lletra is None:
        sortida, cursor = "", 0
        for col, a in acords:
            sortida += " " * max(col - cursor, 1 if sortida else 0) + f"<ch>{a}</ch>"
            cursor = col + len(a)
        return sortida
    lletra = lletra.rstrip()
    final = max((c for c, _ in acords), default=0)
    if len(lletra) < final:
        lletra = lletra.ljust(final)
    sortida, cursor = "", 0
    for col, a in sorted(acords):
        sortida += lletra[cursor:col] + f"<ch>{a}</ch>"
        cursor = col
    return (sortida + lletra[cursor:]).rstrip()


def a_content(linies: list[tuple[str, list[tuple[int, str]] | None]]) -> str:
    """[(text sense acords, acords marcats o None)] → content. Amb acords marcats (llista, potser
    buida) una línia sense marques mai és d'acords; amb None es classifica amb `acords_de_linia`
    (text pla enganxat a mà)."""
    sortida: list[str] = []
    pendents: tuple[list[tuple[int, str]], str] | None = None  # línia d'acords i el text sobrant ("x4")
    començat = False

    def buida_pendents():
        nonlocal pendents
        if pendents:
            acords, resta = pendents
            sortida.append(fusiona(acords, resta) if resta.strip() else fusiona(acords, None))
        pendents = None

    for text, marcats in linies:
        text = text.replace("\t", "    ").rstrip()
        if RE_PUNTEIG.match(text) or (not marcats and RE_DIAGRAMA.match(text)):
            continue
        m = RE_SECCIO.match(text) if not marcats else None
        m2 = RE_SECCIO_DOS_PUNTS.match(text) if not marcats else None
        if (m and not re.fullmatch(r"x?\d+x?|bis", m.group(1).strip(), re.I)) or m2:
            buida_pendents()
            nom, resta = (m.group(1).strip(), m.group(2)) if m else (m2.group(1).strip(), "")
            sortida.append(f"<sec>{nom}</sec>")
            començat = True
            ac = acords_de_linia(resta) if resta.strip() else None
            if ac:
                sortida.append(fusiona([(c - min(x for x, _ in ac), a) for c, a in ac], None))
            continue
        acords = marcats if marcats is not None else acords_de_linia(text)
        resta_buida = not text.strip() or RE_SOBRANT.match(text.strip())
        if acords and (marcats is None or resta_buida):
            buida_pendents()
            pendents = (acords, text if marcats is not None else "")
            començat = True
            continue
        if not text.strip():
            buida_pendents()
            continue
        if not començat:
            continue  # capçalera de la pàgina
        if acords:  # acords marcats dins la mateixa línia de lletra
            buida_pendents()
            sortida.append(fusiona(acords, text))
        elif pendents:
            sortida.append(fusiona(pendents[0], text))
            pendents = None
        else:
            sortida.append(text.strip() if not text.startswith(" ") else text.rstrip())
    buida_pendents()
    return "\n".join(l for l in sortida if l.strip())


def de_text(text: str) -> str:
    """Tab en text pla (enganxada a mà) → content."""
    return a_content([(l, None) for l in text.replace("\r", "").split("\n")])
