"""Petits elements gràfics de l'app: icones de botó, copes de les classificacions i consells (tooltips)."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from functools import cache
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


class Consell:
    """Text que apareix en passar el ratolí per sobre d'un widget (tooltip)."""

    RETARD_MS = 450

    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text = widget, text
        self.finestra: tk.Toplevel | None = None
        self.pendent: str | None = None
        widget.bind("<Enter>", self._programa, add="+")
        widget.bind("<Leave>", self._amaga, add="+")
        widget.bind("<ButtonPress>", self._amaga, add="+")

    def _programa(self, _e=None) -> None:
        self._cancel_la()
        self.pendent = self.widget.after(self.RETARD_MS, self._mostra)

    def _cancel_la(self) -> None:
        if self.pendent:
            self.widget.after_cancel(self.pendent)
            self.pendent = None

    def _mostra(self) -> None:
        if self.finestra or not self.widget.winfo_exists():
            return
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
