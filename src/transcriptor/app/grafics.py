"""Petits elements gràfics de l'app: icones de botó, copes de les classificacions i consells (tooltips)."""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from functools import cache
from pathlib import Path
from tkinter import ttk

# Fonts d'icones de Windows: agafen el color del tema i es veuen nítides a qualsevol escala
FONTS_ICONES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
GLIFS = {
    "desplega": "",  # ChevronDown
    "plega": "",  # ChevronUp
    "visor": "",  # Play
    "esborra": "",  # Delete
}
# Sense font d'icones (fora de Windows): textos curts
TEXTOS = {"desplega": "▾", "plega": "▴", "visor": "Visor", "esborra": "Esborra"}

COLORS_COPA = {1: "#D4A017", 2: "#A8A9AD", 3: "#B06A2C"}  # or, plata, bronze


def font_icones(arrel: tk.Misc) -> str | None:
    disponibles = set(tkfont.families(arrel))
    return next((f for f in FONTS_ICONES if f in disponibles), None)


def text_icona(nom: str, amb_font: bool) -> str:
    return GLIFS[nom] if amb_font else TEXTOS[nom]


def _fosc(color: str, factor: float) -> tuple[int, int, int]:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return int(r * factor), int(g * factor), int(b * factor)


@cache
def copa(posicio: int, mida: int = 20):
    """Copa de color (or, plata o bronze) com a imatge PIL. Es dibuixa a 4× i es redueix per suavitzar-la."""
    from PIL import Image, ImageDraw

    color = COLORS_COPA[posicio]
    s = mida * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def r(*coords: float) -> list[float]:
        return [c * s for c in coords]

    gruix = max(2, round(s * 0.07))
    # Nanses (darrere la copa)
    d.arc(r(0.06, 0.12, 0.38, 0.46), 90, 270, fill=color, width=gruix)
    d.arc(r(0.62, 0.12, 0.94, 0.46), 270, 90, fill=color, width=gruix)
    # Copa: part recta a dalt i mitja el·lipse a baix
    d.rectangle(r(0.22, 0.08, 0.78, 0.32), fill=color)
    d.pieslice(r(0.22, 0.06, 0.78, 0.58), 0, 180, fill=color)
    # Peu
    d.rectangle(r(0.45, 0.56, 0.55, 0.74), fill=color)
    d.rounded_rectangle(r(0.30, 0.72, 0.70, 0.82), radius=s * 0.03, fill=color)
    d.rounded_rectangle(r(0.24, 0.82, 0.76, 0.94), radius=s * 0.03, fill=_fosc(color, 0.8))
    # Reflex
    d.rounded_rectangle(r(0.32, 0.13, 0.39, 0.40), radius=s * 0.03, fill=(255, 255, 255, 110))
    return img.resize((mida, mida), Image.LANCZOS)


@cache
def _sprites(fosc: bool) -> dict | None:
    """Sprites del tema sv_ttk com a imatges PIL (nom → imatge), o None si el tema no hi és."""
    try:
        import sv_ttk
        from PIL import Image
    except ImportError:
        return None
    tema = Path(sv_ttk.__file__).parent / "theme"
    nom = "dark" if fosc else "light"
    try:
        full = Image.open(tema / f"spritesheet_{nom}.png").convert("RGBA")
        info = (tema / f"sprites_{nom}.tcl").read_text(encoding="utf-8")
    except OSError:
        return None
    return {n: full.crop((int(x), int(y), int(x) + int(w), int(y) + int(h)))
            for n, x, y, w, h in re.findall(r"^\s*([\w-]+) (\d+) (\d+) (\d+) (\d+)", info, re.MULTILINE)}


def _estira(sprite, amplada: int, alcada: int, vora: int, vora_y: int | None = None):
    """Estira un sprite a la mida demanada mantenint-ne les vores (com fa ttk amb `-border`)."""
    from PIL import Image

    vx, vy = vora, vora if vora_y is None else vora_y
    sw, sh = sprite.size
    trossos_x = [(0, vx, 0, vx), (vx, sw - vx, vx, amplada - vx), (sw - vx, sw, amplada - vx, amplada)]
    trossos_y = [(0, vy, 0, vy), (vy, sh - vy, vy, alcada - vy), (sh - vy, sh, alcada - vy, alcada)]
    sortida = Image.new("RGBA", (amplada, alcada), (0, 0, 0, 0))
    for sx0, sx1, dx0, dx1 in trossos_x:
        for sy0, sy1, dy0, dy1 in trossos_y:
            if dx1 > dx0 and dy1 > dy0:
                tros = sprite.crop((sx0, sy0, sx1, sy1)).resize((dx1 - dx0, dy1 - dy0), Image.NEAREST)
                sortida.paste(tros, (dx0, dy0))
    return sortida


# Sprites del tema que ttk estén per àrees grans: (amplada, alçada, vora horitzontal, vora vertical).
# ttk no els estira, els enrajola: el centre del marc de les pestanyes (uns 30 px) es copiava milers de
# vegades a cada redibuix, i només això eren ~130 ms de cada canvi de mida de la finestra.
SPRITES_GRANS = {
    "notebook-border": (1000, 1000, 5, 5),  # -border 5
    "sep": (1000, 10, 0, 0),  # la línia dels separadors (horitzontals)
    "scrollbar-trough-vert": (12, 1000, 0, 6),  # -border {0 6}; l'amplada ha de quedar igual
}


def accelera_tema(arrel: tk.Misc, fosc: bool) -> list:
    """Substitueix els sprites de SPRITES_GRANS del tema sv_ttk per versions grans ja estirades, que es
    dibuixen d'un sol cop. Es veuen igual. Retorna les imatges noves, que s'han de mantenir vives."""
    from PIL import ImageTk

    sprites = _sprites(fosc)
    if not sprites:
        return []
    tema = "sv_dark" if fosc else "sv_light"
    guardades = []
    for nom, (amplada, alcada, vx, vy) in SPRITES_GRANS.items():
        try:
            imatge = arrel.tk.globalgetvar(f"ttk::theme::{tema}::I({nom})")
        except tk.TclError:
            continue
        if nom not in sprites:
            continue
        nova = ImageTk.PhotoImage(_estira(sprites[nom], amplada, alcada, vx, vy), master=arrel)
        arrel.tk.call(imatge, "blank")
        arrel.tk.call(imatge, "configure", "-width", 0, "-height", 0)  # que agafi la mida nova
        arrel.tk.call(imatge, "copy", nova)
        guardades.append(nova)
    return guardades


def fons_boto(fosc: bool, accent: bool, estat: str, amplada: int, alcada: int, fons: str):
    """Fons d'un botó del tema (estat: "repos", "sobre" o "premut") ja compost sobre el color de fons.

    Una imatge opaca es dibuixa molt més de pressa que els sprites amb transparència dels botons ttk.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (amplada, alcada), fons)
    nom = "button-" + ("accent-" if accent else "") + {"repos": "rest", "sobre": "hover", "premut": "pressed"}[estat]
    sprites = _sprites(fosc)
    if sprites and nom in sprites:
        img.alpha_composite(_estira(sprites[nom], amplada, alcada, 4))
    else:
        color = ("#005fb8" if accent else ("#2d2d2d" if fosc else "#fdfdfd"))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, amplada - 1, alcada - 1), radius=4, fill=color,
                                              outline=None if accent else ("#3d3d3d" if fosc else "#d0d0d0"))
    return img.convert("RGB")


def color_separador(fosc: bool, fons: str) -> str:
    """Color de la línia dels separadors del tema, compost sobre el fons."""
    sprites = _sprites(fosc)
    if not sprites or "sep" not in sprites:
        return "#3a3a3a" if fosc else "#e5e5e5"
    from PIL import Image

    img = Image.new("RGBA", (1, 1), fons)
    s = sprites["sep"]
    img.alpha_composite(s.crop((s.width // 2, s.height // 2, s.width // 2 + 1, s.height // 2 + 1)))
    return "#{:02x}{:02x}{:02x}".format(*img.getpixel((0, 0))[:3])


class Consell:
    """Text que apareix en passar el ratolí per sobre d'un widget (tooltip).

    Amb `tag`, el widget és un canvas i el consell és per als elements del canvas amb aquesta etiqueta.
    """

    RETARD_MS = 450

    def __init__(self, widget: tk.Widget, text: str, tag: str | None = None):
        self.widget, self.text, self.tag = widget, text, tag
        self.finestra: tk.Toplevel | None = None
        self.pendent: str | None = None
        for seq, ordre in (("<Enter>", self._programa), ("<Leave>", self._amaga), ("<ButtonPress>", self._amaga)):
            if tag:
                widget.tag_bind(tag, seq, ordre, add="+")
            else:
                widget.bind(seq, ordre, add="+")

    def _programa(self, _e=None) -> None:
        self._cancel_la()
        self.pendent = self.widget.after(self.RETARD_MS, self._mostra)

    def _cancel_la(self) -> None:
        if self.pendent:
            self.widget.after_cancel(self.pendent)
            self.pendent = None

    def _mostra(self) -> None:
        self.pendent = None
        if self.finestra or not self.widget.winfo_exists():
            return
        if self.tag:
            caixa = self.widget.bbox(self.tag)
            if not caixa:  # l'element ja no hi és (s'ha redibuixat la llista)
                return
            x0, _, x1, y1 = caixa
            x = self.widget.winfo_rootx() + (x0 + x1) // 2 - int(self.widget.canvasx(0))
            y = self.widget.winfo_rooty() + y1 - int(self.widget.canvasy(0)) + 4
        else:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.finestra = tk.Toplevel(self.widget)
        self.finestra.wm_overrideredirect(True)
        self.finestra.attributes("-topmost", True)
        ttk.Label(self.finestra, text=self.text, padding=(8, 4), relief="solid", borderwidth=1).pack()
        self.finestra.update_idletasks()
        self.finestra.geometry(f"+{x - self.finestra.winfo_width() // 2}+{y}")

    def _amaga(self, _e=None) -> None:
        self._cancel_la()
        if self.finestra:
            self.finestra.destroy()
            self.finestra = None
