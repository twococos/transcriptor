"""App d'escriptori del worker: icona a la barra de tasques + finestra d'estat i configuració.

    pythonw -m transcriptor.app

- El primer cop només es veu la configuració (benvinguda): cal enganxar el token. Un cop desada, la
  finestra té tres pestanyes: "Estat" (la primera), "Classificacions" i "Configuració".
- "Estat": una animació diu què fa el worker (barres que ballen = transcrivint, que respiren = esperant),
  la barra de progrés de la primera descàrrega de models, la copa si és al podi d'alguna classificació i
  les cançons fetes, amb les seves estadístiques desplegables, que s'obren al visor.
- "Classificacions": vegeu classificacions.py. El nom del worker no es configura: el posa l'admin i
  l'app el demana al servidor amb el token (i així el valida).
- La icona (pystray) té un menú: activar/desactivar, obrir la finestra, sortir.
- El worker corre en un fil; desactivar-lo l'atura netament (allibera la feina en curs).
- El procés corre amb prioritat baixa perquè no alenteixi l'ordinador.
"""

from __future__ import annotations

import collections
import logging
import logging.handlers
import math
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, ttk

from .. import __version__, fetes
from ..config import Config
from ..device import detecta
from ..models import EstatDescarrega
from ..worker import Client, EstatWorker, VersioMassaAntiga, Worker
from . import classificacions, detalls, windows
from .grafics import (
    BotoCanvas,
    Consell,
    accelera_tema,
    alcada_etiqueta,
    color_hex,
    color_separador,
    copa,
    font_icones,
    mida_boto,
    opcio_estil,
    sprite_opac,
    text_icona,
)
from .settings import Preferencies, dir_app

log = logging.getLogger("transcriptor.app")

TARONJA = "#e6781e"
COLORS_ACTIVITAT = {
    "processant": TARONJA,
    "descarregant": "#3b82f6",
    "esperant": "#f0b07a",
    "pausa": "#9a9a9a",
    "sense_connexio": "#d9534f",
}


def _configura_logs() -> None:
    fitxer = dir_app() / "transcriptor.log"
    gestor = logging.handlers.RotatingFileHandler(fitxer, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    gestor.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[gestor])
    for soroll in ("httpx", "httpx2", "huggingface_hub", "urllib3", "faster_whisper", "numba"):
        logging.getLogger(soroll).setLevel(logging.WARNING)


def _sense_consoles() -> None:
    """Cap procés fill obre finestra de consola, tampoc els que llancen les llibreries (audio-separator
    i pydub criden ffmpeg): amb pythonw cada crida mostraria un cmd buit un instant."""
    if sys.platform != "win32":
        return
    original = subprocess.Popen.__init__
    noves = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS

    def init(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0)
        if not flags & noves:
            kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init


def _sortides_nul_les() -> None:
    """Amb pythonw no hi ha consola i sys.stdout/stderr són None: torch.hub i tqdm hi escriuen el progrés
    de les descàrregues i petarien ("'NoneType' object has no attribute 'write'")."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 — viu tant com el procés
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _icona(actiu: bool):
    from PIL import Image, ImageDraw

    mida = 64
    img = Image.new("RGBA", (mida, mida), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (230, 120, 30) if actiu else (140, 140, 140)  # taronja = treballant
    d.ellipse((2, 2, mida - 2, mida - 2), fill=color)
    # Una corxera estilitzada
    d.ellipse((16, 38, 32, 52), fill="white")
    d.rectangle((28, 12, 33, 46), fill="white")
    d.polygon([(33, 12), (48, 20), (48, 27), (33, 19)], fill="white")
    return img


def _mida(b: float) -> str:
    if b >= 1e9:
        return f"{b / 1e9:.1f} GB".replace(".", ",")
    if b >= 1e6:
        return f"{b / 1e6:.0f} MB"
    return f"{b / 1e3:.0f} kB"


def _durada(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def _rellotge(s: float) -> str:
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def _data(epoch: float) -> str:
    t = time.localtime(epoch)
    avui = time.localtime()
    if t.tm_year == avui.tm_year and t.tm_yday == avui.tm_yday:
        return f"avui {t.tm_hour}:{t.tm_min:02d}"
    if t.tm_year == avui.tm_year and t.tm_yday == avui.tm_yday - 1:
        return f"ahir {t.tm_hour}:{t.tm_min:02d}"
    return f"{t.tm_mday}/{t.tm_mon}/{t.tm_year}"


def _fons() -> str:
    return opcio_estil("TFrame", "background", defecte="#fafafa")


class Activitat(tk.Canvas):
    """Barres d'equalitzador: ballen quan transcriu, ones quan descarrega, respiren quan espera."""

    N, AMPLE, ALT, GRUIX = 5, 76, 52, 9

    def __init__(self, pare, fosc: bool):
        super().__init__(pare, width=self.AMPLE, height=self.ALT, bg=_fons(), highlightthickness=0)
        self.mode = "aturat"
        self.color_aturat = "#4a4a4a" if fosc else "#cfcfcf"
        self.t0 = time.monotonic()
        pas = self.AMPLE / self.N
        self.xs = [pas * (i + 0.5) for i in range(self.N)]
        self.barres = [self.create_line(x, 0, x, 0, width=self.GRUIX, capstyle="round") for x in self.xs]
        self._anima()

    def _alcada(self, i: int, t: float) -> float:
        if self.mode == "processant":  # sinusoides de freqüències diferents: sembla música
            return 0.2 + 0.8 * abs(math.sin(t * (2.3 + 0.55 * i) + i * 1.7) * math.sin(t * 0.9 + i))
        if self.mode == "descarregant":
            return 0.25 + 0.55 * (0.5 + 0.5 * math.sin(t * 4 - i * 0.9))
        if self.mode in ("esperant", "pausa", "sense_connexio"):
            return 0.15 + 0.15 * (0.5 + 0.5 * math.sin(t * 1.5 - i * 0.6))
        return 0.1

    def _anima(self) -> None:
        t = time.monotonic() - self.t0
        marge = self.GRUIX / 2 + 1
        util = self.ALT - 2 * marge
        color = COLORS_ACTIVITAT.get(self.mode, self.color_aturat)
        for i, (x, b) in enumerate(zip(self.xs, self.barres)):
            h = max(self._alcada(i, t), 0.02) * util
            mig = self.ALT / 2
            self.coords(b, x, mig - h / 2, x, mig + h / 2)
            self.itemconfigure(b, fill=color)
        rapid = self.mode in ("processant", "descarregant")
        self.after(40 if rapid else (90 if self.mode != "aturat" else 500), self._anima)


class Capcalera(tk.Canvas):
    """La part de dalt de la pestanya d'estat (animació, estat, botó d'activar, comptadors, dispositiu, podi) i
    la barra "Les teves cançons", dibuixades en un sol canvas pel mateix motiu que LlistaFetes: cada widget
    ttk del tema costa de redibuixar. L'App hi posa les dades amb `posa(...)` i només es redibuixa si canvien.
    """

    ESPAI_ANIMACIO = 14

    def __init__(self, pare, app: "App"):
        super().__init__(pare, bg=_fons(), highlightthickness=0, height=1)
        self.app = app
        self.activitat = Activitat(self, app.fosc)
        self.finestra_animacio = self.create_window(0, 0, window=self.activitat, anchor="nw")
        self.dades: dict = {"titol": "Aturat", "detall": "", "boto": ("Activa", True), "progres": None,
                            "comptadors": "", "dispositiu": "", "podi": None, "total": None}
        self.dibuixat: tuple | None = None
        self.amplada = 0
        self.botons: list[BotoCanvas] = []
        self.consell_podi: Consell | None = None
        self.lligams_podi: list[tuple[str, str]] = []
        self.imatges: dict = {}
        self.fons = color_hex(self, _fons())
        self.color_text = opcio_estil("TLabel", "foreground", defecte="#1c1c1c")
        self.color_secundari = opcio_estil("Secundari.TLabel", "foreground", defecte="#6b6b6b")
        self.color_accent = opcio_estil("Accent.TLabel", "foreground", defecte=TARONJA)
        self.color_linia = color_separador(app.fosc, self.fons)
        self.font_text = opcio_estil("TLabel", "font", defecte="TkDefaultFont")
        self.font_estat = opcio_estil("Estat.TLabel", "font", defecte=self.font_text)
        self.font_seccio = opcio_estil("Seccio.TLabel", "font", defecte=self.font_text)
        self.font_accent = opcio_estil("Accent.TLabel", "font", defecte=self.font_text)
        self.alt_text = alcada_etiqueta(self, "Secundari.TLabel")
        self.alt_estat = alcada_etiqueta(self, "Estat.TLabel")
        self.alt_seccio = alcada_etiqueta(self, "Seccio.TLabel")
        self.bind("<Configure>", self._canvi_mida)

    def posa(self, **dades) -> None:
        self.dades.update(dades)
        self._dibuixa()

    def _canvi_mida(self, e) -> None:
        if e.width != self.amplada:
            self.amplada = e.width
            self._dibuixa(forca=True)

    def _imatge(self, clau: tuple, crea):
        from PIL import ImageTk

        if clau not in self.imatges:
            self.imatges[clau] = ImageTk.PhotoImage(crea(), master=self)
        return self.imatges[clau]

    @staticmethod
    def _mig(alt_caixa: int, alt_etiqueta: int) -> int:
        """On va el centre d'un text centrat verticalment en una caixa, arrodonit com ho fa una etiqueta ttk."""
        return (alt_caixa - alt_etiqueta) // 2 + alt_etiqueta // 2

    def _mida_boto(self, text: str, estil: str) -> tuple[int, int]:
        clau = ("mida", text, estil)
        if clau not in self.imatges:
            self.imatges[clau] = mida_boto(self, text, estil)
        return self.imatges[clau]

    def _boto(self, x: int, y: int, text: str, estil: str, ordre, actiu: bool = True, ipadx: int = 0) -> int:
        w, h = self._mida_boto(text, estil)
        self.botons.append(BotoCanvas(self, x, y, w + 2 * ipadx, h, text, estil, ordre, self.app.fosc, self.fons,
                                      actiu=actiu))
        return w + 2 * ipadx

    def _dibuixa(self, forca: bool = False) -> None:
        clau = (self.amplada, repr(sorted(self.dades.items())))
        if clau == self.dibuixat and not forca:
            return
        self.dibuixat = clau
        for b in self.botons:
            b.destrueix()
        self.botons.clear()
        if self.consell_podi:
            self.consell_podi.desvincula()
            self.consell_podi = None
        for seq, funcio in self.lligams_podi:
            self.tag_unbind("podi", seq, funcio)
        self.lligams_podi = []
        # Tot menys l'animació, que és un widget: treure-la i tornar-la a posar la faria parpellejar
        for item in self.find_all():
            if item != self.finestra_animacio:
                self.delete(item)
        d, amplada = self.dades, self.amplada or self.winfo_width()

        # Animació a l'esquerra i, al costat, l'estat amb el detall a sota (centrats verticalment)
        x = Activitat.AMPLE + self.ESPAI_ANIMACIO
        detall = self.create_text(x, 0, anchor="nw", text=d["detall"], width=360, font=self.font_text,
                                  fill=self.color_secundari)
        caixa = self.bbox(detall)
        alt_detall = max(self.alt_text, caixa[3] - caixa[1]) if caixa and d["detall"] else self.alt_text
        alt_textos = self.alt_estat + alt_detall
        y_textos = max(0, (Activitat.ALT - alt_textos) // 2)
        self.create_text(x, y_textos + self.alt_estat // 2, anchor="w", text=d["titol"], font=self.font_estat,
                         fill=self.color_text)
        self.coords(detall, x, y_textos + self.alt_estat)
        y = max(Activitat.ALT, alt_textos)

        if d["progres"] is not None:  # només mentre es baixen els models
            fraccio, text = d["progres"]
            y += 12
            w = max(amplada, 10)
            fons = sprite_opac(self.app.fosc, "progressbar-trough-hor", w, 5, 1, self.fons)
            if fons is not None:
                self.create_image(0, y, anchor="nw", image=self._imatge(("solc", w), lambda: fons))
            else:
                self.create_rectangle(0, y + 2, w, y + 3, fill=self.color_linia, outline="")
            ple = int(w * min(max(fraccio, 0.0), 1.0))
            if ple >= 4:
                barra = sprite_opac(self.app.fosc, "progressbar-bar-hor", ple, 5, 2, self.fons)
                if barra is not None:  # canvia cada segon: no es guarda a la memòria cau
                    from PIL import ImageTk

                    self.imatges["barra"] = ImageTk.PhotoImage(barra, master=self)
                    self.create_image(0, y, anchor="nw", image=self.imatges["barra"])
                else:
                    self.create_rectangle(0, y + 1, ple, y + 4, fill="#005fb8", outline="")
            y += 5 + 4
            self.create_text(0, y + self.alt_text // 2, anchor="w", text=text, font=self.font_text,
                             fill=self.color_secundari)
            y += self.alt_text

        # Botó d'activar i, al costat, els comptadors de la sessió
        y += 14
        text, actiu = d["boto"]
        _, alt_boto = self._mida_boto(text, "Accent.TButton")
        w = self._boto(0, y, text, "Accent.TButton", self.app.commuta, actiu=actiu, ipadx=18)
        self.create_text(w + 12, y + self._mig(alt_boto, self.alt_text), anchor="w", text=d["comptadors"], font=self.font_text,
                         fill=self.color_secundari)
        y += alt_boto + 8
        self.create_text(0, y + self.alt_text // 2, anchor="w", text=d["dispositiu"], font=self.font_text,
                         fill=self.color_secundari)
        y += self.alt_text

        if d["podi"] is not None:  # al podi d'alguna classificació: la copa i on (clicar-hi porta a la pestanya)
            posicio, text, consell = d["podi"]
            y += 6
            from PIL import Image

            def crea_copa():
                img = Image.new("RGBA", (18, 18), self.fons)
                img.alpha_composite(copa(posicio, 18))
                return img.convert("RGB")

            alt = max(18, self.alt_text)
            self.create_image(0, y + alt // 2, anchor="w", image=self._imatge(("copa", posicio), crea_copa),
                              tags="podi")
            self.create_text(18 + 6, y + alt // 2, anchor="w", text=text, font=self.font_accent,
                             fill=self.color_accent, tags="podi")
            accions = (("<Enter>", lambda _e: self.configure(cursor="hand2")),
                       ("<Leave>", lambda _e: self.configure(cursor="")),
                       ("<Button-1>", lambda _e: self.app.pestanyes.select(self.app.pestanya_classificacions)))
            self.lligams_podi = [(seq, self.tag_bind("podi", seq, accio)) for seq, accio in accions]
            self.consell_podi = Consell(self, consell, "podi")
            y += alt
        else:
            self.configure(cursor="")

        # Separador i la barra "Les teves cançons" (amb el total i el botó d'esborrar-les a la dreta)
        y += 14
        self.create_rectangle(0, y, amplada, y + 1, fill=self.color_linia, outline="")
        y += 1 + 14
        w_boto, alt_boto = self._mida_boto("Esborra-les totes", "TButton")
        alt_barra = max(self.alt_seccio, alt_boto)
        self.create_text(0, y + self._mig(alt_barra, self.alt_seccio), anchor="w", text="Les teves cançons", font=self.font_seccio,
                         fill=self.color_text)
        if d["total"] is not None:
            self._boto(amplada - w_boto, y + (alt_barra - alt_boto) // 2, "Esborra-les totes", "TButton",
                       self.app.esborra_totes)
            self.create_text(amplada - w_boto - 8, y + self._mig(alt_barra, self.alt_text), anchor="e", text=d["total"],
                             font=self.font_text, fill=self.color_secundari)
        y += alt_barra + 6
        if int(self.cget("height")) != y:
            self.configure(height=y)
        for b in self.botons:
            b.ratoli_a_sobre()


class LlistaFetes(ttk.Frame):
    """Llista desplaçable de les cançons fetes, cadascuna amb els botons de detalls, del visor i d'esborrar.

    Tota la llista és un sol canvas dibuixat (textos, línies i botons fets d'imatges opaques), no pas un
    widget ttk per element: amb el tema sv_ttk cada widget costa uns quants mil·lisegons de redibuixar, i
    amb una desena de cançons canviar la mida de la finestra trigava gairebé un segon.

    Només hi pot haver una cançó desplegada. Els detalls es dibuixen per sota de tot i les files de sota
    (cada una amb el seu fons opac) els tapen i es desplacen per destapar-los: així s'anima sense refer res,
    i la vista es mou perquè la fila clicada no es desplaci de la pantalla.
    """

    DURADA_ANIMACIO_MS = 220
    PAS_MS = 15
    SEPARACIO = 6  # espai a cada costat de la línia entre cançons
    ESPAI_BOTONS = 4

    def __init__(self, pare, app: "App"):
        super().__init__(pare)
        self.app = app
        self.fetes: list[fetes.Feta] = []
        self.oberta: Path | None = None
        self.alcades: dict[Path, int] = {}  # alçada visible dels detalls de cada cançó que en té de dibuixats
        self.completes: dict[Path, int] = {}  # i l'alçada que ocupen desplegats del tot
        self.ys: list[int] = []  # on és dibuixada cada fila
        self.botons: dict[tuple[int, int], BotoCanvas] = {}  # (fila, 0 esborra / 1 visor / 2 detalls)
        self.animacio: str | None = None
        self.amplada = 0
        self.canvas = tk.Canvas(self, bg=_fons(), highlightthickness=0, height=150)
        barra = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=barra.set)
        self.canvas.bind("<Configure>", self._canvi_mida)
        self.canvas.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", self._roda, add="+")
        self._mesures()

    def _mesures(self) -> None:
        """Colors, fonts i mides dels botons, presos del tema perquè la llista sigui igual que la resta."""
        self.fons = color_hex(self, _fons())
        self.color_text = opcio_estil("TLabel", "foreground", defecte="#1c1c1c")
        self.color_secundari = opcio_estil("Secundari.TLabel", "foreground", defecte="#6b6b6b")
        self.color_linia = color_separador(self.app.fosc, self.fons)
        self.font_nom = opcio_estil("Canco.TLabel", "font", defecte="TkDefaultFont")
        self.font_text = opcio_estil("TLabel", "font", defecte="TkDefaultFont")
        self.amb_icones = bool(self.app.font_icones)
        self.estil_boto = "Icona.TButton" if self.amb_icones else "TButton"
        self.mesura_nom = tkfont.Font(font=self.font_nom)
        self.mesura_text = tkfont.Font(font=self.font_text)
        self.alt_nom = alcada_etiqueta(self, "Canco.TLabel")
        self.alt_text = alcada_etiqueta(self, "Secundari.TLabel")
        # La mida dels botons, la d'un botó ttk real amb el mateix estil
        self.mides_boto = {icona: mida_boto(self, text_icona(icona, self.amb_icones), self.estil_boto,
                                            width=3 if self.amb_icones else 0)
                           for icona in ("desplega", "plega", "visor", "esborra")}
        self.alt_boto = max(h for _, h in self.mides_boto.values())
        self.alt_fila = max(self.alt_nom + self.alt_text, self.alt_boto + 6)

    def _roda(self, e) -> None:
        if not self.winfo_exists():
            return
        sota = self.winfo_containing(e.x_root, e.y_root)
        if sota is not None and str(sota).startswith(str(self)) and self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(-1 * (e.delta // 120), "units")

    def _canvi_mida(self, e) -> None:
        if e.width != self.amplada:  # canviar només l'alçada no demana redibuixar res
            self.amplada = e.width
            self._atura_animacio()
            self._dibuixa()

    def mostra(self, llista: list[fetes.Feta]) -> None:
        self._atura_animacio()
        self.fetes = llista
        if self.oberta not in {f.dir for f in llista}:
            self.oberta = None
        inici = self.canvas.yview()[0]  # en refer la llista (cançó nova, esborrada) no es torna a dalt
        self._dibuixa()
        self.canvas.yview_moveto(inici)

    # ── Dibuix ──────────────────────────────────────────────────────────────
    def _posicions(self) -> tuple[list[int], int]:
        ys, y = [], 0
        for i, feta in enumerate(self.fetes):
            if i:
                y += 2 * self.SEPARACIO + 1
            ys.append(y)
            y += self.alt_fila + self.alcades.get(feta.dir, 0)
        return ys, y

    def _dibuixa(self) -> None:
        c = self.canvas
        for boto in self.botons.values():
            boto.destrueix()
        self.botons.clear()
        c.delete("all")
        amplada = self.amplada or c.winfo_width()
        if not self.fetes:
            self.alcades.clear()
            c.create_text(0, 8, anchor="nw", width=min(420, max(amplada, 100)), font=self.font_text,
                          fill=self.color_secundari,
                          text="Encara no n'hi ha cap. Quan el worker acabi una cançó, la podràs obrir al visor "
                               "per veure com ha quedat la lletra i els acords sincronitzats amb la música.")
            c.configure(scrollregion=(0, 0, amplada, 0))
            return
        # Primer totes les files com si no hi hagués detalls; després _recoloca les baixa on toca
        self.alcades, self.completes = {}, {}
        self.ys, _ = self._posicions()
        for i, feta in enumerate(self.fetes):
            self._dibuixa_fila(i, feta, self.ys[i], amplada)
            if feta.dir == self.oberta:  # sense animació: ja desplegada
                self.alcades[feta.dir] = self._dibuixa_detalls(i, feta, self.ys[i] + self.alt_fila)
        # Cortina sota l'última fila: tapa els detalls que encara no s'han de veure
        c.create_rectangle(0, 0, 0, 0, fill=self.fons, outline="", tags="cortina")
        self._recoloca()

    def _dibuixa_fila(self, i: int, feta: fetes.Feta, y: int, amplada: int) -> None:
        c = self.canvas
        fila = f"f{i}"
        # Fons opac (amb la línia de sobre): tapa els detalls de la fila anterior mentre es despleguen
        dalt = y - (2 * self.SEPARACIO + 1 if i else 0)
        c.create_rectangle(0, dalt, amplada, y + self.alt_fila, fill=self.fons, outline="", tags=fila)
        if i:
            c.create_rectangle(0, y - self.SEPARACIO - 1, amplada, y - self.SEPARACIO, fill=self.color_linia,
                               outline="", tags=fila)
        # Botons, de dreta a esquerra: si no hi cap tot, s'escurça el text i no pas els botons
        x = amplada
        oberta = feta.dir == self.oberta
        botons = (
            ("esborra", "Esborra", lambda: self.app.esborra(feta), False),
            ("visor", "Obre al visor", lambda: self.app.obre_visor(feta), True),
            ("plega" if oberta else "desplega", "Amaga els detalls" if oberta else "Detalls",
             lambda: self._commuta(feta), False),
        )
        for k, (icona, consell, ordre, accent) in enumerate(botons):
            w, h = self.mides_boto[icona]
            x -= w
            estil = ("Icona." if self.amb_icones else "") + ("Accent.TButton" if accent else "TButton")
            self.botons[(i, k)] = BotoCanvas(c, x, y + (self.alt_fila - h) // 2, w, h,
                                             text_icona(icona, self.amb_icones), estil, ordre, self.app.fosc,
                                             self.fons, consell, tags=(fila,))
            x -= self.ESPAI_BOTONS
        resum = [_data(feta.data)]
        if feta.segons:
            resum.append(f"{_durada(feta.segons)} de càlcul")
        resum.append(_mida(feta.mida) if feta.te_audio else "YouTube")
        lloc = x - 8
        c.create_text(0, y + self.alt_nom // 2, anchor="w", text=_retalla(feta.nom, self.mesura_nom, lloc),
                      font=self.font_nom, fill=self.color_text, tags=fila)
        c.create_text(0, y + self.alt_nom + self.alt_text // 2, anchor="w",
                      text=_retalla(" · ".join(resum), self.mesura_text, lloc), font=self.font_text,
                      fill=self.color_secundari, tags=fila)

    def _dibuixa_detalls(self, i: int, feta: fetes.Feta, y: int) -> int:
        """Dibuixa els detalls d'una cançó sota la fila, per sota de tot (les files de sota els tapen).
        Retorna l'alçada que ocupen."""
        c = self.canvas
        tag = f"d{i}"
        inici = y
        y += 6
        x = 12
        grups = detalls.grups(fetes.stats_de(feta))
        if not grups:
            c.create_text(x, y, anchor="nw", text="No hi ha dades d'aquesta cançó.", font=self.font_text,
                          fill=self.color_secundari, tags=tag)
            y += self.alt_text
        else:
            columna = x + max(self.mesura_text.measure(e) for _, camps in grups for e, _ in camps) + 12
            for g, (titol, camps) in enumerate(grups):
                y += 6 if g else 0
                c.create_text(x, y, anchor="nw", text=titol, font=self.font_nom, fill=self.color_text, tags=tag)
                y += self.alt_nom + 1
                for etiqueta, valor in camps:
                    c.create_text(x, y, anchor="nw", text=etiqueta, font=self.font_text, fill=self.color_secundari,
                                  tags=tag)
                    v = c.create_text(columna, y, anchor="nw", text=valor, font=self.font_text, width=260,
                                      fill=self.color_text, tags=tag)
                    caixa = c.bbox(v)
                    y += max(self.alt_text, caixa[3] - caixa[1] if caixa else 0)
        c.tag_lower(tag)
        self.completes[feta.dir] = y + 2 - inici
        return self.completes[feta.dir]

    def _recoloca(self) -> int:
        """Mou les files a la seva posició segons l'alçada actual dels detalls. Retorna l'alçada total."""
        ys, total = self._posicions()
        for i, (abans, ara) in enumerate(zip(self.ys, ys)):
            if ara != abans:
                self.canvas.move(f"f{i}", 0, ara - abans)
                self.canvas.move(f"d{i}", 0, ara - abans)
        self.ys = ys
        amplada = self.amplada or self.canvas.winfo_width()
        self.canvas.coords("cortina", 0, total, amplada, total + 10000)
        self.canvas.configure(scrollregion=(0, 0, amplada, total))
        return total

    # ── Desplegar i plegar ──────────────────────────────────────────────────
    def _commuta(self, feta: fetes.Feta) -> None:
        self._atura_animacio()
        index = {f.dir: i for i, f in enumerate(self.fetes)}
        if feta.dir not in index:
            return
        i = index[feta.dir]
        anterior, self.oberta = self.oberta, (None if self.oberta == feta.dir else feta.dir)
        # On és la fila clicada dins la vista: s'hi ha de quedar mentre canvien les alçades
        y_vista = self.ys[i] - self.canvas.canvasy(0)
        y_final = y_vista
        canvis = {}  # cançó → (alçada inicial, alçada final)
        if anterior is not None and anterior in index:
            self._icona_detalls(index[anterior], obert=False)
            canvis[anterior] = (self.alcades.get(anterior, 0), 0)
        if self.oberta is not None:
            self._icona_detalls(i, obert=True)
            alcada = self._dibuixa_detalls(i, feta, self.ys[i] + self.alt_fila)
            self.alcades[feta.dir] = 0
            canvis[feta.dir] = (0, alcada)
            # Si els detalls no hi caben per sota, la vista baixa fins a mostrar-los, sense amagar la fila
            if y_vista >= 0:
                y_final = min(y_vista, max(self.canvas.winfo_height() - self.alt_fila - alcada, 0))
        self._pas(canvis, i, y_vista, y_final, time.monotonic())

    def _icona_detalls(self, i: int, obert: bool) -> None:
        boto = self.botons[(i, 2)]
        boto.posa_text(text_icona("plega" if obert else "desplega", self.amb_icones))
        boto.consell.text = "Amaga els detalls" if obert else "Detalls"

    def _pas(self, canvis: dict, i: int, y_vista: float, y_final: float, t0: float) -> None:
        """Un fotograma de l'animació. Va per temps i no per passos: sempre dura el mateix."""
        t = min(1.0, (time.monotonic() - t0) * 1000 / self.DURADA_ANIMACIO_MS)
        f = 1 - (1 - t) ** 3  # ease-out cúbic
        for dir_, (h0, h1) in canvis.items():
            self.alcades[dir_] = round(h0 + (h1 - h0) * f)
        total = self._recoloca()
        y = self.ys[i] - (y_vista + (y_final - y_vista) * f)
        self.canvas.yview_moveto(max(0.0, y) / total if total else 0)
        if t < 1:
            self.animacio = self.after(self.PAS_MS, self._pas, canvis, i, y_vista, y_final, t0)
        else:
            self.animacio = None
            self._acaba()

    def _acaba(self) -> None:
        """Esborra els detalls que han quedat plegats."""
        index = {f.dir: i for i, f in enumerate(self.fetes)}
        for dir_ in [d for d in self.alcades if d != self.oberta]:
            del self.alcades[dir_]
            self.completes.pop(dir_, None)
            if dir_ in index:
                self.canvas.delete(f"d{index[dir_]}")
        self._recoloca()

    def _atura_animacio(self) -> None:
        """Si hi ha una animació a mitges, la deixa de cop en l'estat final."""
        if self.animacio is None:
            return
        self.after_cancel(self.animacio)
        self.animacio = None
        if self.oberta in self.alcades:
            self.alcades[self.oberta] = self.completes[self.oberta]
        self._acaba()


def _retalla(text: str, font: tkfont.Font, amplada: int) -> str:
    """Escurça el text amb "…" perquè no passi de l'amplada donada (en píxels)."""
    mesura = font.measure
    if amplada <= 0 or mesura(text) <= amplada:
        return text
    while text and mesura(text + "…") > amplada:
        text = text[:-1]
    return text.rstrip() + "…"


class App:
    def __init__(self) -> None:
        self.prefs = Preferencies.carrega()
        self.cues: queue.Queue = queue.Queue()  # actualitzacions d'estat des del fil del worker
        self.worker: Worker | None = None
        self.fil: threading.Thread | None = None
        self.estat = EstatWorker()
        self.perfil = None
        self.icona = None
        self.icona_activa = False
        self.descarrega: EstatDescarrega | None = None
        self.mostres: collections.deque = collections.deque(maxlen=20)  # (temps, bytes) per a la velocitat
        self.bytes_descarregats = 0
        self.aturant = False
        self.visors: dict[Path, str] = {}  # directori de la cançó → URL del seu servidor
        self.n_historial = 0
        self.font_icones: str | None = None
        self.classificacions, self.classificacions_rebut = classificacions.carrega_desades()
        self.classificacions_demanades = 0.0  # time.monotonic() de l'última petició
        self.error_token: str | None = None

        self.arrel = tk.Tk()
        self.arrel.title("Transcriptor")
        self.arrel.geometry("540x700")
        self.arrel.minsize(480, 560)
        self.arrel.protocol("WM_DELETE_WINDOW", self.amaga)
        self._tema()
        self._vars()
        self.contingut: ttk.Frame | None = None
        if self.prefs.token_protegit:
            self._construeix_principal()
        else:
            self._construeix_benvinguda()
        self.arrel.after(300, self._processa_cua)
        self.arrel.after(1000, self._tic)

    # ── Aparença ────────────────────────────────────────────────────────────
    def _tema(self) -> None:
        from PIL import ImageTk

        self.fosc = windows.tema_fosc()
        try:
            import sv_ttk

            sv_ttk.set_theme("dark" if self.fosc else "light")
            # El tema posa els colors i la font base en rebre <<ThemeChanged>>, que arriba més tard: sense
            # això, els canvas (que no són ttk) es crearien amb el fons clar per defecte
            self.arrel.tk.call("configure_colors")
            self._sprites_grans = accelera_tema(self.arrel, self.fosc)
        except Exception:  # noqa: BLE001 — sense el tema, tkinter per defecte
            log.warning("No s'ha pogut carregar el tema sv_ttk", exc_info=True)
        self._foto_icona = ImageTk.PhotoImage(_icona(True))
        self.arrel.iconphoto(True, self._foto_icona)
        estil = ttk.Style()
        secundari = "#9a9a9a" if self.fosc else "#6b6b6b"
        estil.configure("Titol.TLabel", font=("Segoe UI Semibold", 20))
        estil.configure("Estat.TLabel", font=("Segoe UI Semibold", 15))
        estil.configure("Seccio.TLabel", font=("Segoe UI Semibold", 12))
        estil.configure("Canco.TLabel", font=("Segoe UI Semibold", 10))
        estil.configure("Secundari.TLabel", foreground=secundari)
        estil.configure("Accent.TLabel", foreground=TARONJA, font=("Segoe UI Semibold", 10))
        estil.configure("Error.TLabel", foreground="#d9534f")
        self.font_icones = font_icones(self.arrel)
        if self.font_icones:
            for base in ("TButton", "Accent.TButton"):
                estil.configure(f"Icona.{base}", font=(self.font_icones, 10), padding=(6, 4))

    def _vars(self) -> None:
        p = self.prefs
        self.var_api = tk.StringVar(value=p.api)
        self.var_token = tk.StringVar(value="●" * 8 if p.token_protegit else "")
        self.var_nom = tk.StringVar(value=p.nom_worker or "—")  # el nom que li ha posat l'admin
        self.var_fils = tk.IntVar(value=p.max_fils)
        self.var_inactiu = tk.BooleanVar(value=p.nomes_inactiu)
        self.var_arrencada = tk.BooleanVar(value=windows.arrencada_activa())
        self.var_auto = tk.BooleanVar(value=p.actiu)
        self.var_audio = tk.BooleanVar(value=p.desa_audio)

    def _capcalera(self, pare) -> None:
        c = ttk.Frame(pare)
        c.pack(fill="x", pady=(0, 12))
        ttk.Label(c, text="Transcriptor", style="Titol.TLabel").pack(side="left")
        ttk.Label(c, text=f"v{__version__}", style="Secundari.TLabel").pack(side="left", padx=8, pady=(10, 0))
        ttk.Label(c, text="per a El Cançoner", style="Accent.TLabel").pack(side="right", pady=(10, 0))

    # ── Vistes ──────────────────────────────────────────────────────────────
    def _nou_contingut(self) -> ttk.Frame:
        if self.contingut:
            self.contingut.destroy()
        self.contingut = ttk.Frame(self.arrel, padding=(20, 16))
        self.contingut.pack(fill="both", expand=True)
        self._capcalera(self.contingut)
        return self.contingut

    def _construeix_benvinguda(self) -> None:
        f = self._nou_contingut()
        self.pestanyes = None
        ttk.Label(f, text="Benvingut/da!", style="Estat.TLabel").pack(anchor="w")
        ttk.Label(f, wraplength=480, justify="left", text=(
            "El Transcriptor fa servir aquest ordinador per treure la lletra, els acords i el ritme de "
            "cançons per a El Cançoner. Per començar, enganxa el token que t'han donat i desa. Després, prem Activa: el primer "
            "cop baixarà els models (~1,8 GB).")
        ).pack(anchor="w", pady=(4, 14))
        self._formulari(f, benvinguda=True)

    def _construeix_principal(self) -> None:
        f = self._nou_contingut()
        self.pestanyes = ttk.Notebook(f)
        self.pestanyes.pack(fill="both", expand=True)
        estat = ttk.Frame(self.pestanyes, padding=(14, 14))
        self.pestanya_classificacions = classificacions.PestanyaClassificacions(
            self.pestanyes, lambda: self._actualitza_classificacions(forca=True))
        config = ttk.Frame(self.pestanyes, padding=(14, 14))
        self.pestanyes.add(estat, text="  Estat  ")
        self.pestanyes.add(self.pestanya_classificacions, text="  Classificacions  ")
        self.pestanyes.add(config, text="  Configuració  ")
        self._pestanya_estat(estat)
        self._formulari(config, benvinguda=False)
        self.pestanyes.bind("<<NotebookTabChanged>>", self._canvi_pestanya)
        self._recarrega_fetes()
        self._mostra_classificacions()
        self._refresca()
        self._actualitza_jo()
        self._actualitza_classificacions()

    def _pestanya_estat(self, f) -> None:
        self.capcalera = Capcalera(f, self)
        self.capcalera.pack(fill="x")
        self.activitat = self.capcalera.activitat
        self.llista = LlistaFetes(f, self)
        self.llista.pack(fill="both", expand=True)

    def _formulari(self, f, benvinguda: bool) -> None:
        g = ttk.Frame(f)
        g.pack(fill="x")
        files: list[tuple[str, tk.Widget]] = [("Token", ttk.Entry(g, textvariable=self.var_token, show="●")),
                                              ("Servidor", ttk.Entry(g, textvariable=self.var_api))]
        if not benvinguda:
            files.append(("Nom al Cançoner", ttk.Label(g, textvariable=self.var_nom, style="Canco.TLabel")))
            files.append(("Nuclis (0 = tots)", ttk.Spinbox(g, from_=0, to=64, textvariable=self.var_fils, width=6)))
        for i, (etiqueta, camp) in enumerate(files):
            ttk.Label(g, text=etiqueta).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=4)
            camp.grid(row=i, column=1, sticky="w" if isinstance(camp, (ttk.Spinbox, ttk.Label)) else "ew", pady=4)
            if isinstance(camp, ttk.Label):
                Consell(camp, "El nom el posa l'administrador quan crea el token")
        g.columnconfigure(1, weight=1)
        self.lbl_error_token = ttk.Label(f, text=self.error_token or "", style="Error.TLabel", wraplength=460)
        self.lbl_error_token.pack(anchor="w")
        if benvinguda:
            files[0][1].focus_set()

        o = ttk.Frame(f)
        o.pack(fill="x", pady=(12, 0))
        for text, var in [("Només quan no faig servir l'ordinador (5 min sense teclat ni ratolí)", self.var_inactiu),
                          ("Arrenca amb Windows", self.var_arrencada),
                          ("Comença a treballar en obrir l'app", self.var_auto),
                          ("Desa l'àudio de les cançons fetes per al visor (~3 MB cadascuna)", self.var_audio)]:
            ttk.Checkbutton(o, text=text, variable=var, style="Switch.TCheckbutton").pack(anchor="w", pady=3)

        b = ttk.Frame(f)
        b.pack(fill="x", pady=(18, 0))
        ttk.Button(b, text="Desa", style="Accent.TButton",
                   command=self.desa).pack(side="left", ipadx=12)
        if not benvinguda:
            ttk.Button(b, text="Obre el registre", command=self.obre_registre).pack(side="left", padx=8)
            self.lbl_desat = ttk.Label(b, text="", style="Secundari.TLabel")
            self.lbl_desat.pack(side="left", padx=4)

    # ── Estat ───────────────────────────────────────────────────────────────
    def _descarregant(self) -> bool:
        d = self.descarrega
        return bool(d and d.total and not d.acabat and self.fil and self.fil.is_alive())

    def _fase(self) -> str:
        if self._descarregant():
            return "descarregant"
        if self.fil and self.fil.is_alive():
            return self.estat.fase if self.estat.fase != "aturat" else "engegant"
        return "aturat"

    def _textos(self, fase: str) -> tuple[str, str]:
        e = self.estat
        if self.aturant and fase != "aturat":
            return "Aturant…", ("La cançó torna a la cua perquè la pugui fer un altre ordinador. "
                                "S'atura en acabar el càlcul que té entre mans (uns segons).")
        if fase == "descarregant":
            d = self.descarrega
            return "Descarregant els models", f"Pas {d.i} de {d.n}: {d.pas}. Només cal el primer cop."
        if fase == "processant":
            fa = f" · fa {_durada(time.time() - e.inici_feina)}" if e.inici_feina else ""
            detall = f"{e.feina_actual or ''}{fa}"
            if e.pas_feina:
                temps = f" · {_rellotge(time.time() - e.inici_pas)}" if e.inici_pas else ""
                detall += f"\nPas {e.i_pas} de {e.n_passos}: {e.pas_feina}{temps}"
            return "Transcrivint una cançó", detall
        if fase == "esperant":
            return "Esperant feina", "Ara no hi ha cap cançó a la cua. Ho tornarà a mirar d'aquí a una estona."
        if fase == "pausa":
            motiu = e.missatge.removeprefix("En pausa: ")
            return "En pausa", f"Ara {motiu}: continuarà sol quan deixis de fer-lo servir."
        if fase == "sense_connexio":
            return "Sense connexió", e.missatge
        if fase == "engegant":
            return "Engegant…", e.missatge
        error = f"\nÚltim error: {e.ultim_error}" if e.ultim_error else ""
        return "Aturat", "Activa'l perquè l'ordinador ajudi a transcriure cançons." + error

    def _refresca(self) -> None:
        fase = self._fase()
        if self.icona:
            actiu = fase != "aturat"
            if actiu != self.icona_activa:
                self.icona.icon = _icona(actiu)
                self.icona_activa = actiu
            titol = f"Transcriptor — {self._textos(fase)[0]}"
            if self.icona.title != titol:
                self.icona.title = titol
        if not self.pestanyes:
            return
        titol, detall = self._textos(fase)
        self.activitat.mode = "aturat" if self.aturant else ("esperant" if fase == "engegant" else fase)

        if fase == "descarregant":
            boto = ("Descarregant models…", False)
        elif self.aturant and fase != "aturat":
            boto = ("Aturant…", False)
        else:
            boto = ("Desactiva" if fase != "aturat" else "Activa", True)

        progres = None
        if fase == "descarregant":
            d = self.descarrega
            text = f"{_mida(self.bytes_descarregats)} de {_mida(d.total)}"
            velocitat = self._velocitat()
            if velocitat > 10_000:
                queden = (d.total - self.bytes_descarregats) / velocitat
                mbs = f"{velocitat / 1e6:.1f}".replace(".", ",")
                text += f" · {mbs} MB/s · queden uns {_durada(max(queden, 60))}"
            progres = (self.bytes_descarregats / max(d.total, 1), text)

        e = self.estat
        parts = []
        if e.fetes or e.fallades:
            parts.append(f"Aquesta sessió: {e.fetes} fetes" + (f", {e.fallades} fallades" if e.fallades else ""))
        if e.fetes:
            parts.append(f"{e.temps_mitja_s / 60:.0f} min de mitjana")
        dispositiu = f"Treballa amb: {self.perfil.device.upper()} — {self.perfil.nom}" if self.perfil else ""
        self.capcalera.posa(titol=titol, detall=detall, boto=boto, progres=progres, comptadors=" · ".join(parts),
                            dispositiu=dispositiu)

    def _velocitat(self) -> float:
        if len(self.mostres) < 3:
            return 0.0
        (t0, b0), (t1, b1) = self.mostres[0], self.mostres[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0

    def _tic(self) -> None:
        """Cada segon: progrés de la descàrrega i textos amb temps ("fa 3 min")."""
        if self._descarregant():
            self.bytes_descarregats = self.descarrega.bytes()
            self.mostres.append((time.monotonic(), self.bytes_descarregats))
        else:
            self.mostres.clear()
        self._refresca()
        self.arrel.after(1000, self._tic)

    def _recarrega_fetes(self) -> None:
        if not self.pestanyes:
            return
        llista = fetes.llista()
        self.llista.mostra(llista)
        self.capcalera.posa(total=f"{len(llista)} · {_mida(sum(f.mida for f in llista))}" if llista else None)

    def _processa_cua(self) -> None:
        try:
            while True:
                tipus, dades = self.cues.get_nowait()
                if tipus == "estat":
                    self.estat = dades
                elif tipus == "fetes":
                    self._recarrega_fetes()
                elif tipus == "mostra":
                    self._mostra_ara()
                elif tipus == "acabat":
                    self.aturant = False
                elif tipus == "error":
                    self.aturant = False
                    messagebox.showerror("Transcriptor", dades)
                elif tipus == "jo":
                    self._rep_jo(*dades)
                elif tipus == "classificacions":
                    self._rep_classificacions(*dades)
                elif tipus == "actualitza_classificacions":
                    self._actualitza_classificacions(forca=True)
                self._refresca()
        except queue.Empty:
            pass
        self.arrel.after(300, self._processa_cua)

    # ── Accions ─────────────────────────────────────────────────────────────
    def desa(self) -> None:
        primer_cop = not self.pestanyes
        token = self.var_token.get().strip()
        if primer_cop and not token:
            messagebox.showwarning("Transcriptor", "Enganxa el token que t'han donat per poder començar.")
            return
        api_nova = self.var_api.get().strip()
        connexio_nova = api_nova != self.prefs.api
        self.prefs.api = api_nova
        if token and set(token) != {"●"}:
            self.prefs.token = token
            self.var_token.set("●" * 8)
            connexio_nova = True
        try:
            self.prefs.max_fils = int(self.var_fils.get() or 0)
        except (tk.TclError, ValueError):
            self.prefs.max_fils = 0
        self.prefs.nomes_inactiu = self.var_inactiu.get()
        self.prefs.actiu = self.var_auto.get()
        self.prefs.desa_audio = self.var_audio.get()
        self.prefs.arrencar_amb_windows = self.var_arrencada.get()
        windows.configura_arrencada(self.prefs.arrencar_amb_windows, ordre_arrencada())
        self.prefs.desa()

        if primer_cop:
            self._construeix_principal()  # ja comprova el token
            return
        if connexio_nova:
            self.var_nom.set("Comprovant el token…")
            self._actualitza_jo()
            self._actualitza_classificacions(forca=True)
        avis = "Desat ✓"
        if self.fil and self.fil.is_alive():
            avis += "  (el servidor i el token s'aplicaran quan el tornis a activar)"
        self.lbl_desat.config(text=avis)
        self.arrel.after(5000, lambda: self.lbl_desat.winfo_exists() and self.lbl_desat.config(text=""))

    def obre_registre(self) -> None:
        webbrowser.open((dir_app() / "transcriptor.log").as_uri())

    def obre_visor(self, feta: fetes.Feta) -> None:
        url = self.visors.get(feta.dir)
        if not url:
            from ..visor import inicia

            try:
                srv, url, _analisi, _audio = inicia(feta.dir)
            except (OSError, ValueError) as e:
                messagebox.showerror("Transcriptor", f"No s'ha pogut obrir el visor: {e}")
                return
            threading.Thread(target=srv.serve_forever, daemon=True, name=f"visor-{feta.dir.name}").start()
            self.visors[feta.dir] = url
        webbrowser.open(url + ("?tema=fosc" if self.fosc else "?tema=clar"))  # el visor segueix el tema de l'app

    def esborra(self, feta: fetes.Feta) -> None:
        if messagebox.askyesno("Transcriptor", f"Vols esborrar «{feta.nom}» d'aquest ordinador?\n\n"
                                               "A El Cançoner no s'esborra res."):
            fetes.esborra(feta)
            self._recarrega_fetes()

    def esborra_totes(self) -> None:
        llista = fetes.llista()
        if llista and messagebox.askyesno(
                "Transcriptor", f"Vols esborrar les {len(llista)} cançons desades en aquest ordinador "
                                f"({_mida(sum(f.mida for f in llista))})?\n\nA El Cançoner no s'esborra res."):
            fetes.esborra_totes()
            self._recarrega_fetes()

    def _pot_treballar(self) -> str | None:
        if self.prefs.nomes_inactiu:
            inactiu = windows.segons_inactiu()
            if inactiu < self.prefs.minuts_inactiu * 60:
                return "l'ordinador s'està fent servir"
        return None

    def _desa_feta(self, feina: dict, res, wav: Path, segons: float) -> None:
        fetes.desa(feina["id"], feina, res.analisi.model_dump_json(), wav, segons, self.prefs.desa_audio,
                   stats=res.estadistiques)
        self.cues.put(("fetes", None))
        self.cues.put(("actualitza_classificacions", None))

    # ── Servidor: nom del worker i classificacions ──────────────────────────
    def _client(self) -> Client:
        return Client(self.prefs.api, self.prefs.token, windows_nom(), None)

    def _en_fil(self, crida, tipus: str) -> None:
        """Fa `crida(client)` en un fil i n'envia (resultat, error) a la cua com a `tipus`."""
        if not self.prefs.token:
            return

        def corre() -> None:
            try:
                self.cues.put((tipus, (crida(self._client()), None)))
            except PermissionError:
                self.cues.put((tipus, (None, "token")))
            except VersioMassaAntiga as e:
                self.cues.put((tipus, (None, f"Cal actualitzar el Transcriptor (versió mínima {e})")))
            except Exception as e:  # noqa: BLE001 — sense connexió, servidor antic (404)…
                log.info("Petició al servidor fallida (%s): %s", tipus, e)
                self.cues.put((tipus, (None, "connexio")))

        threading.Thread(target=corre, daemon=True, name=tipus).start()

    def _actualitza_jo(self) -> None:
        self._en_fil(lambda c: c.jo(), "jo")

    def _rep_jo(self, jo: dict | None, error: str | None) -> None:
        if jo:
            self.error_token = None
            if jo.get("name") and jo["name"] != self.prefs.nom_worker:
                self.prefs.nom_worker = jo["name"]
                self.prefs.desa()
        elif error == "token":
            self.error_token = "El servidor no reconeix aquest token (incorrecte o revocat). Revisa'l i desa."
            if self.pestanyes:
                self.pestanyes.select(2)
        elif error and error != "connexio":
            self.error_token = error
        self.var_nom.set(self.prefs.nom_worker or "—")
        if self.lbl_error_token.winfo_exists():
            self.lbl_error_token.config(text=self.error_token or "")

    def _actualitza_classificacions(self, forca: bool = False) -> None:
        """Com a molt un cop cada 5 min si no es força (en obrir la pestanya); sempre després d'una cançó."""
        if not forca and time.monotonic() - self.classificacions_demanades < 300 and self.classificacions_demanades:
            return
        self.classificacions_demanades = time.monotonic()
        self._en_fil(lambda c: c.classificacions(), "classificacions")

    def _rep_classificacions(self, dades: dict | None, error: str | None) -> None:
        if dades:
            for avis in classificacions.millores(self.classificacions, dades):
                self._notifica(avis + "!")
            self.classificacions, self.classificacions_rebut = dades, time.time()
            classificacions.desa(dades)
            if (dades.get("me") or {}).get("name") and dades["me"]["name"] != self.prefs.nom_worker:
                self.prefs.nom_worker = dades["me"]["name"]
                self.prefs.desa()
                self.var_nom.set(self.prefs.nom_worker)
        textos_error = {"connexio": "Sense connexió", "token": "Token rebutjat"}
        self._mostra_classificacions(textos_error.get(error, error) if error else None)

    def _mostra_classificacions(self, error: str | None = None) -> None:
        if not self.pestanyes:
            return
        self.pestanya_classificacions.mostra(self.classificacions, self.classificacions_rebut, error)
        podis = classificacions.destacades(self.classificacions)
        if podis:
            rank, text = podis[0]
            self.capcalera.posa(podi=(rank, text + (f"  (+{len(podis) - 1})" if len(podis) > 1 else ""),
                                      "\n".join(t for _r, t in podis)))
        else:
            self.capcalera.posa(podi=None)

    def _canvi_pestanya(self, _e=None) -> None:
        if self.pestanyes.select() == str(self.pestanya_classificacions):
            self.pestanya_classificacions.refresca_rebut()
            self._actualitza_classificacions()

    def _notifica(self, text: str) -> None:
        if self.icona:
            try:
                self.icona.notify(text, "Transcriptor")
            except Exception:  # noqa: BLE001 — les notificacions no són imprescindibles
                log.debug("No s'ha pogut mostrar la notificació", exc_info=True)

    def activa(self) -> None:
        if self.fil and self.fil.is_alive():
            return
        if not self.prefs.token:
            messagebox.showwarning("Transcriptor", "Primer enganxa el token que t'han donat i desa.")
            return
        perfil = detecta(self.prefs.dispositiu)
        if self.prefs.max_fils:
            perfil = replace(perfil, fils=self.prefs.max_fils)
        self.perfil = perfil
        client = Client(self.prefs.api, self.prefs.token, windows_nom(), perfil)
        self.worker = Worker(client, Config(), perfil, en_canvi=lambda e: self.cues.put(("estat", e)),
                             pot_treballar=self._pot_treballar, en_feta=self._desa_feta)
        self.descarrega = EstatDescarrega()
        self.estat = self.worker.estat
        self.aturant = False

        def corre() -> None:
            try:
                self._prepara_models()
                if not self.worker.atura.is_set():
                    self.worker.bucle()
            except VersioMassaAntiga as e:
                self.cues.put(("error", f"Cal actualitzar el Transcriptor (versió mínima {e})."))
            except PermissionError as e:
                self.cues.put(("error", f"El servidor ha rebutjat el token: {e}"))
            except Exception as e:  # noqa: BLE001
                log.exception("Error del worker")
                self.estat.ultim_error = str(e)[:300]
                self.cues.put(("error", f"Hi ha hagut un error inesperat:\n\n{e}\n\n"
                                        "En tens els detalls al registre (Configuració → Obre el registre)."))
            finally:
                self.cues.put(("acabat", None))

        self.fil = threading.Thread(target=corre, daemon=True, name="worker")
        self.fil.start()
        self._refresca()

    def _prepara_models(self) -> None:
        from ..models import prepara

        def progres(missatge: str, i: int, n: int) -> None:
            self.estat.missatge = f"Preparant models ({i}/{n}): {missatge}"
            self.cues.put(("estat", self.estat))

        prepara(self.perfil, Config(), progres, self.descarrega)

    def desactiva(self) -> None:
        if self.worker and self.fil and self.fil.is_alive():
            self.worker.atura.set()
            self.aturant = True
            self._refresca()

    def commuta(self) -> None:
        if self._descarregant() or self.aturant:
            return
        if self.fil and self.fil.is_alive():
            self.desactiva()
        else:
            self.activa()

    def mostra(self) -> None:
        """Es pot cridar des de qualsevol fil (icona, una altra instància): ho fa el fil de tkinter."""
        self.cues.put(("mostra", None))

    def _mostra_ara(self) -> None:
        self.arrel.deiconify()
        if self.arrel.state() == "iconic":
            self.arrel.state("normal")
        # Windows no deixa passar al davant una finestra d'un procés en segon pla: "topmost" un moment
        self.arrel.attributes("-topmost", True)
        self.arrel.lift()
        self.arrel.focus_force()
        self.arrel.after(300, lambda: self.arrel.attributes("-topmost", False))

    def amaga(self) -> None:
        self.arrel.withdraw()

    def surt(self) -> None:
        self.desactiva()
        if self.fil:
            self.fil.join(timeout=10)
        if self.icona:
            self.icona.stop()
        self.arrel.after(0, self.arrel.destroy)

    def executa(self, amagat: bool = False) -> None:
        """`amagat`: només a la icona (arrencada amb Windows). Si no, sempre es veu la finestra."""
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Obre", lambda: self.mostra(), default=True),
            pystray.MenuItem(lambda _i: "Desactiva" if self._fase() != "aturat" else "Activa",
                             lambda: self.arrel.after(0, self.commuta)),
            pystray.MenuItem("Surt", lambda: self.arrel.after(0, self.surt)),
        )
        self.icona = pystray.Icon("transcriptor", _icona(False), "Transcriptor", menu)
        self.icona.run_detached()
        if amagat:
            self.arrel.withdraw()
        if self.prefs.actiu and self.prefs.token_protegit:
            self.activa()
        if windows.arrencada_activa():  # una arrencada desada per una versió anterior (sense --amagat)
            windows.configura_arrencada(True, ordre_arrencada())
        self._refresca()
        self.arrel.mainloop()


def ordre_arrencada() -> str:
    """L'ordre de l'arrencada amb Windows: comença amagada, només amb la icona."""
    return f'"{sys.executable.replace("python.exe", "pythonw.exe")}" -m transcriptor.app --amagat'


def windows_nom() -> str:
    import platform

    return platform.node() or "worker"


def main() -> None:
    _sortides_nul_les()
    _sense_consoles()
    # Models, cache i àudio temporal fora del directori d'instal·lació
    base = os.environ.get("LOCALAPPDATA") or str(dir_app())
    os.environ.setdefault("TX_HOME", os.path.join(base, "Transcriptor", "dades"))
    _configura_logs()
    app: App | None = None
    pendent = threading.Event()  # una altra instància ha demanat la finestra abans que l'app existís

    def en_mostra() -> None:
        if app:
            app.mostra()
        else:
            pendent.set()

    if not windows.instancia_unica(en_mostra):
        log.info("Ja hi ha un Transcriptor obert: se li ha demanat que mostri la finestra")
        return
    windows.prioritat_baixa()
    app = App()
    if pendent.is_set():
        app.mostra()
    app.executa(amagat="--amagat" in sys.argv)


if __name__ == "__main__":
    main()
