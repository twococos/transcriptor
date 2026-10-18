"""Petits elements gràfics de l'app: icones de botó, copes de les classificacions i consells (tooltips)."""

from __future__ import annotations

import itertools
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
    for element, (estil, estats, opcions, mida) in ELEMENTS_RAPIDS.items():
        guardades += _element_rapid(arrel, sprites, element, estil, estats, opcions, mida)
    return guardades


def _estats_boto(prefix: str) -> list[tuple[str, str]]:
    return [("", f"{prefix}-rest"), ("selected disabled", f"{prefix}-dis"), ("disabled", f"{prefix}-dis"),
            ("selected", f"{prefix}-rest"), ("pressed", f"{prefix}-pressed"),
            ("active focus", f"{prefix}-focus-hover"), ("active", f"{prefix}-hover"), ("focus", f"{prefix}-focus")]


# Elements del tema amb sprites petits i vora, que no es poden fer grans sense fer gran l'element (en pren
# la mida mínima): es creen elements nous amb els sprites ja estirats i `-width 0 -height 0`, amb els
# mateixos estats i opcions que a sv_ttk/theme/*.tcl, i se substitueixen a la disposició de l'estil.
# element → (estil, [(estats, sprite)], opcions de l'element, mida dels sprites estirats)
ELEMENTS_RAPIDS = {
    "Notebook.tab": ("TNotebook.Tab", [("", "tab-rest"), ("selected", "tab-selected"), ("active", "tab-hover")],
                     {"border": 13, "padding": (16, 14, 16, 6), "height": 32}, (600, 32)),
    "Button.button": ("TButton", _estats_boto("button"), {"border": 4, "sticky": "nsew"}, (600, 120)),
    "AccentButton.button": ("Accent.TButton", _estats_boto("button-accent"), {"border": 4, "sticky": "nsew"},
                            (600, 120)),
}


def _element_rapid(arrel: tk.Misc, sprites: dict, element: str, estil_ttk: str, estats: list[tuple[str, str]],
                   opcions: dict, mida: tuple[int, int]) -> list:
    from PIL import ImageTk

    if not all(s in sprites for _, s in estats):
        return []
    vora = opcions["border"]
    imatges = {s: ImageTk.PhotoImage(_estira(sprites[s], *mida, vora), master=arrel) for _, s in estats}
    nou = f"Rapid.{element}"
    estil = ttk.Style(arrel)
    try:
        estil.element_create(nou, "image", imatges[estats[0][1]],
                             *((e, imatges[s]) for e, s in estats[1:]), **{"width": 0, "height": 0, **opcions})
    except tk.TclError:  # ja creat (el tema només es carrega un cop, però per si de cas)
        return []

    def canvia(disposicio):
        return [(nou if nom == element else nom,
                 {**op, "children": canvia(op["children"])} if "children" in op else op)
                for nom, op in disposicio]

    estil.layout(estil_ttk, canvia(estil.layout(estil_ttk)))
    return list(imatges.values())


def opcio_estil(estil: str, opcio: str, estat: str | None = None, defecte: str = "") -> str:
    """Valor d'una opció d'un estil ttk com a text (lookup pot tornar objectes Tcl)."""
    return str(ttk.Style().lookup(estil, opcio, [estat] if estat else None) or "") or defecte


def color_hex(widget: tk.Misc, color: str) -> str:
    """Qualsevol color de Tk en hexadecimal (sense el tema, el fons és "SystemButtonFace", que PIL no entén)."""
    return "#{:02x}{:02x}{:02x}".format(*(v // 257 for v in widget.winfo_rgb(color)))


def sprite_opac(fosc: bool, nom: str, amplada: int, alcada: int, vora: int, fons: str):
    """Un sprite del tema estirat a la mida donada i compost sobre el color de fons (imatge PIL opaca, o None
    sense el tema). Una imatge opaca d'un sol tros es dibuixa molt més de pressa que l'element ttk."""
    from PIL import Image

    sprites = _sprites(fosc)
    if not sprites or nom not in sprites:
        return None
    img = Image.new("RGBA", (amplada, alcada), fons)
    img.alpha_composite(_estira(sprites[nom], amplada, alcada, vora))
    return img.convert("RGB")


ESTATS_BOTO = {"repos": "rest", "sobre": "hover", "premut": "pressed", "desactivat": "dis"}


def fons_boto(fosc: bool, accent: bool, estat: str, amplada: int, alcada: int, fons: str):
    """Fons d'un botó del tema (estat: "repos", "sobre", "premut" o "desactivat") compost sobre el fons."""
    from PIL import Image, ImageDraw

    nom = "button-" + ("accent-" if accent else "") + ESTATS_BOTO[estat]
    img = sprite_opac(fosc, nom, amplada, alcada, 4, fons)
    if img is None:
        img = Image.new("RGB", (amplada, alcada), fons)
        color = ("#005fb8" if accent else ("#2d2d2d" if fosc else "#fdfdfd"))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, amplada - 1, alcada - 1), radius=4, fill=color,
                                              outline=None if accent else ("#3d3d3d" if fosc else "#d0d0d0"))
    return img


def mida_boto(pare: tk.Misc, text: str, estil: str, **opcions) -> tuple[int, int]:
    """La mida que tindria un ttk.Button real amb aquest text i estil."""
    b = ttk.Button(pare, text=text, style=estil, **opcions)
    mida = (b.winfo_reqwidth(), b.winfo_reqheight())
    b.destroy()
    return mida


_numeros = itertools.count()
SEQUENCIES_BOTO = ("<Enter>", "<Leave>", "<ButtonPress-1>", "<ButtonRelease-1>")


def alcada_etiqueta(pare: tk.Misc, estil: str) -> int:
    """L'alçada d'un ttk.Label d'una línia amb aquest estil (no és ben bé la de la font: un píxel menys)."""
    e = ttk.Label(pare, text="Àg", style=estil)
    alcada = e.winfo_reqheight()
    e.destroy()
    return alcada


class BotoCanvas:
    """Botó del tema dibuixat dins un canvas: la imatge de fons (repòs, a sobre, premut o desactivat) i el
    text o la icona a sobre. Es veu com un ttk.Button però es redibuixa molt més de pressa (vegeu
    accelera_tema). `tags` s'afegeixen als dos elements, per moure'ls junts."""

    def __init__(self, canvas: tk.Canvas, x: int, y: int, amplada: int, alcada: int, text: str, estil: str,
                 ordre, fosc: bool, fons: str, consell: str | None = None, tags: tuple = (), actiu: bool = True):
        self.c, self.amplada, self.alcada, self.ordre = canvas, amplada, alcada, ordre
        self.fosc, self.fons, self.actiu = fosc, fons, actiu
        self.accent = "Accent" in estil
        self.tag = f"boto{next(_numeros)}"
        defecte = opcio_estil("TButton", "foreground", defecte="#1c1c1c")
        self.colors = {e: opcio_estil(estil, "foreground", s, defecte=defecte)
                       for e, s in (("repos", None), ("sobre", "active"), ("premut", "pressed"),
                                    ("desactivat", "disabled"))}
        estat = "repos" if actiu else "desactivat"
        self.fons_id = canvas.create_image(x, y, anchor="nw", image=self._imatge(estat), tags=(*tags, self.tag))
        # El text no rep el ratolí (state=disabled): així entrar-hi no és sortir de la imatge
        # El text dels botons ttk queda mig píxel amunt: el farciment és de 2 a dalt i 3 a baix
        self.text_id = canvas.create_text(x + amplada // 2, y + (alcada - 1) // 2, text=text, state="disabled",
                                          font=opcio_estil(estil, "font", defecte="TkDefaultFont"),
                                          disabledfill=self.colors[estat], tags=(*tags, self.tag))
        accions = (lambda _e: self._estat("sobre"), lambda _e: self._estat("repos"),
                   lambda _e: self._estat("premut"), self._deixa_anar)
        # Els identificadors, per poder-ne esborrar les comandes Tcl en destruir el botó
        self.lligams = [(seq, canvas.tag_bind(self.fons_id, seq, accio)) for seq, accio in zip(SEQUENCIES_BOTO, accions)]
        self.consell = Consell(canvas, consell, self.tag) if consell else None

    def _imatge(self, estat: str):
        from PIL import ImageTk

        cache = self.c.__dict__.setdefault("_imatges_boto", {})  # una per canvas: hi han de quedar vives
        clau = (self.accent, estat, self.amplada, self.alcada)
        if clau not in cache:
            cache[clau] = ImageTk.PhotoImage(
                fons_boto(self.fosc, self.accent, estat, self.amplada, self.alcada, self.fons), master=self.c)
        return cache[clau]

    def _estat(self, nom: str) -> None:
        nom = nom if self.actiu else "desactivat"
        self.c.itemconfigure(self.fons_id, image=self._imatge(nom))
        self.c.itemconfigure(self.text_id, disabledfill=self.colors[nom])

    def _deixa_anar(self, e) -> None:
        x0, y0, x1, y1 = self.c.bbox(self.fons_id) or (0, 0, 0, 0)
        dins = x0 <= self.c.canvasx(e.x) <= x1 and y0 <= self.c.canvasy(e.y) <= y1
        self._estat("sobre" if dins else "repos")
        if dins and self.actiu:
            self.ordre()

    def posa_text(self, text: str) -> None:
        self.c.itemconfigure(self.text_id, text=text)

    def ratoli_a_sobre(self) -> None:
        """Si el ratolí ja hi és a sobre (el botó s'acaba de redibuixar), es mostra com a tal."""
        x = self.c.canvasx(self.c.winfo_pointerx() - self.c.winfo_rootx())
        y = self.c.canvasy(self.c.winfo_pointery() - self.c.winfo_rooty())
        x0, y0, x1, y1 = self.c.bbox(self.fons_id) or (0, 0, -1, -1)
        if x0 <= x <= x1 and y0 <= y <= y1:
            self._estat("sobre")

    def destrueix(self) -> None:
        """Treu les vinculacions d'esdeveniments (Tk les guarda encara que s'esborrin els elements)."""
        for seq, funcio in self.lligams:
            self.c.tag_unbind(self.fons_id, seq, funcio)
        if self.consell:
            self.consell.desvincula()


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
        self.lligams = []
        for seq, ordre in (("<Enter>", self._programa), ("<Leave>", self.amaga), ("<ButtonPress>", self.amaga)):
            if tag:
                self.lligams.append((seq, widget.tag_bind(tag, seq, ordre, add="+")))
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

    def desvincula(self) -> None:
        """Per als consells d'elements d'un canvas que s'esborren: treu les vinculacions de l'etiqueta."""
        self.amaga()
        for seq, funcio in self.lligams:  # també n'esborra la comanda Tcl
            self.widget.tag_unbind(self.tag, seq, funcio)
        self.lligams = []

    def amaga(self, _e=None) -> None:
        self._cancel_la()
        if self.finestra:
            self.finestra.destroy()
            self.finestra = None
