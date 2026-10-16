"""Text de les estadístiques d'una cançó feta (el desplegable de la llista), agrupat per temes.

Els camps coneguts surten amb etiqueta i format; la resta (camps que el worker hi afegeixi més
endavant, p. ex. dins `checks`) surten al grup "Altres" amb el seu camí, sense tocar res aquí.
"""

from __future__ import annotations

from ..estadistiques import NOMS_ETAPES

FONTS_LLETRA = {
    "user": "enganxada a mà",
    "db": "la de El Cançoner",
    "lrclib": "LRCLIB",
    "whisper": "desxifrada de l'àudio (Whisper)",
    "cap": "cap",
}

Grup = tuple[str, list[tuple[str, str]]]


def durada(s: float | None) -> str:
    if s is None:
        return "—"
    s = int(round(s))
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{round(x * 100)} %"


def _aplana(obj: dict, prefix: str = "") -> list[tuple[str, object]]:
    out = []
    for k, v in obj.items():
        cami = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(_aplana(v, cami))
        else:
            out.append((cami, v))
    return out


def grups(stats: dict) -> list[Grup]:
    """[(títol del grup, [(etiqueta, valor)])], sense els grups buits."""
    usats: set[str] = set()

    def pren(cami: str):
        usats.add(cami)
        v: object = stats
        for k in cami.split("."):
            if not isinstance(v, dict):
                return None
            v = v.get(k)
        return v

    def g(cami: str, defecte=None):
        v = pren(cami)
        return defecte if v is None else v

    # Temps
    temps: list[tuple[str, str]] = []
    total = g("timing.wall_s") or g("timing.total_s")
    pren("timing.total_s")
    if total is not None:
        temps.append(("Total", durada(total)))
    for clau, s in (g("timing.stages_s", {}) or {}).items():
        usats.add(f"timing.stages_s.{clau}")
        temps.append((NOMS_ETAPES.get(clau, clau), durada(s)))
    if cache := g("timing.cached", []):
        temps.append(("De la cache", ", ".join(NOMS_ETAPES.get(c, c).lower() for c in cache)))
    if (d := g("audio.duration_s")) is not None:
        temps.append(("Durada de la cançó", durada(d)))

    # Màquina
    maquina: list[tuple[str, str]] = []
    tipus, nom = g("device.type"), g("device.name")
    if tipus or nom:
        extra = []
        if (fils := g("device.threads")):
            extra.append(f"{fils} fils")
        if (vram := g("device.vram_gb")):
            extra.append(f"{vram:g} GB")
        text = f"{'GPU' if tipus == 'cuda' else 'CPU'} — {nom or '?'}"
        maquina.append(("Dispositiu", text + (f" ({', '.join(extra)})" if extra else "")))
    if (versio := g("app_version")):
        maquina.append(("Versió de l'app", versio))
    pren("v")

    # Lletra
    lletra: list[tuple[str, str]] = []
    if (font := g("lyrics.source")):
        lletra.append(("Font", FONTS_LLETRA.get(font, font)))
    pren("lyrics.align")
    if (r := g("lyrics.matched_ratio")) is not None:
        lletra.append(("Text ancorat a l'àudio", pct(r)))
    if (r := g("lyrics.timed_ratio")) is not None:
        lletra.append(("Paraules amb temps propi", pct(r)))
    if (r := g("lyrics.asr_mean_conf")) is not None:
        lletra.append(("Confiança de Whisper", pct(r)))
    if (n := g("lyrics.discarded_lines")):
        lletra.append(("Línies descartades", str(n)))
    paraules, linies = g("lyrics.words"), g("lyrics.lines")
    if paraules is not None:
        lletra.append(("Paraules / línies", f"{paraules} / {linies if linies is not None else '?'}"))

    # Música
    musica: list[tuple[str, str]] = []
    if (to := g("key.label")):
        text = to
        if (c := g("key.confidence")) is not None:
            text += f" · confiança {pct(c)}"
        if (capo := g("key.capo")):
            text += f" · cejilla al {capo}"
        musica.append(("To", text))
    pren("key.capo")
    if (bpm := g("tempo.bpm")) is not None:
        musica.append(("Tempo", f"{round(bpm)} BPM · {g('tempo.time_signature', '?')}"))
    pren("tempo.time_signature")
    if (n := g("chords.count")) is not None:
        text = f"{n}"
        if (dif := g("chords.distinct")) is not None:
            text += f" ({dif} diferents)"
        if (c := g("chords.mean_conf")) is not None:
            text += f" · confiança {pct(c)}"
        musica.append(("Acords", text))
    pren("chords.vocabulary")
    if (n := g("structure.sections")) is not None:
        musica.append(("Seccions", str(n)))

    avisos = [("·", a) for a in (g("warnings", []) or [])]

    # Models i qualsevol camp desconegut
    models = [(k.removeprefix("models."), str(v)) for k, v in _aplana(stats) if k.startswith("models.")]
    altres = [(k, ", ".join(map(str, v)) if isinstance(v, list) else str(v))
              for k, v in _aplana(stats)
              if k not in usats and not k.startswith(("models.", "timing.stages_s.")) and v not in (None, [], {})]

    return [(t, files) for t, files in [("Temps", temps), ("Màquina", maquina), ("Lletra", lletra),
                                        ("Música", musica), ("Avisos", avisos), ("Models", models),
                                        ("Altres", altres)] if files]
