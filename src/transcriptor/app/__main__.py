"""App d'escriptori del worker: icona a la barra de tasques + finestra d'estat i configuració.

    pythonw -m transcriptor.app

- El primer cop només es veu la configuració (benvinguda): cal enganxar el token. Un cop desada, la
  finestra té dues pestanyes: "Estat" (la primera) i "Configuració".
- "Estat": una animació diu què fa el worker (barres que ballen = transcrivint, que respiren = esperant),
  la barra de progrés de la primera descàrrega de models i les cançons fetes, que s'obren al visor.
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
import webbrowser
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, ttk

from .. import __version__, fetes
from ..config import Config
from ..device import detecta
from ..models import EstatDescarrega
from ..worker import Client, EstatWorker, VersioMassaAntiga, Worker
from . import windows
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
    return ttk.Style().lookup("TFrame", "background") or "#fafafa"


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


class LlistaFetes(ttk.Frame):
    """Llista desplaçable de les cançons fetes, cadascuna amb els botons del visor i d'esborrar."""

    def __init__(self, pare, app: "App"):
        super().__init__(pare)
        self.app = app
        self.canvas = tk.Canvas(self, bg=_fons(), highlightthickness=0, height=150)
        barra = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=barra.set)
        self.interior = ttk.Frame(self.canvas)
        self.finestra = self.canvas.create_window(0, 0, window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.finestra, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.bind_all("<MouseWheel>", self._roda, add="+")

    def _roda(self, e) -> None:
        if not self.winfo_exists():
            return
        sota = self.winfo_containing(e.x_root, e.y_root)
        if sota is not None and str(sota).startswith(str(self)) and self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(-1 * (e.delta // 120), "units")

    def mostra(self, llista: list[fetes.Feta]) -> None:
        for w in self.interior.winfo_children():
            w.destroy()
        if not llista:
            ttk.Label(self.interior, style="Secundari.TLabel", wraplength=420, justify="left",
                      text="Encara no n'hi ha cap. Quan el worker acabi una cançó, la podràs obrir al visor "
                           "per veure com ha quedat la lletra i els acords sincronitzats amb la música.",
                      ).pack(anchor="w", pady=8)
            return
        for i, feta in enumerate(llista):
            if i:
                ttk.Separator(self.interior).pack(fill="x", pady=6)
            fila = ttk.Frame(self.interior)
            fila.pack(fill="x")
            # Els botons primer: si no hi cap tot, s'escurça el text i no pas els botons
            ttk.Button(fila, text="Esborra", command=lambda f=feta: self.app.esborra(f)).pack(side="right")
            ttk.Button(fila, text="Obre al visor", style="Accent.TButton",
                       command=lambda f=feta: self.app.obre_visor(f)).pack(side="right", padx=6)
            text = ttk.Frame(fila)
            text.pack(side="left", fill="x", expand=True)
            nom = feta.nom if len(feta.nom) <= 34 else feta.nom[:33] + "…"
            ttk.Label(text, text=nom, style="Canco.TLabel").pack(anchor="w")
            detalls = [_data(feta.data)]
            if feta.segons:
                detalls.append(f"{_durada(feta.segons)} de càlcul")
            detalls.append(_mida(feta.mida) if feta.te_audio else "YouTube")
            ttk.Label(text, text=" · ".join(detalls), style="Secundari.TLabel").pack(anchor="w")
        self.canvas.yview_moveto(0)


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

    def _vars(self) -> None:
        p = self.prefs
        self.var_api = tk.StringVar(value=p.api)
        self.var_token = tk.StringVar(value="●" * 8 if p.token_protegit else "")
        self.var_nom = tk.StringVar(value=p.nom_worker)
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
        config = ttk.Frame(self.pestanyes, padding=(14, 14))
        self.pestanyes.add(estat, text="  Estat  ")
        self.pestanyes.add(config, text="  Configuració  ")
        self._pestanya_estat(estat)
        self._formulari(config, benvinguda=False)
        self._recarrega_fetes()
        self._refresca()

    def _pestanya_estat(self, f) -> None:
        dalt = ttk.Frame(f)
        dalt.pack(fill="x")
        self.activitat = Activitat(dalt, self.fosc)
        self.activitat.pack(side="left", padx=(0, 14))
        textos = ttk.Frame(dalt)
        textos.pack(side="left", fill="x", expand=True)
        self.lbl_estat = ttk.Label(textos, text="Aturat", style="Estat.TLabel")
        self.lbl_estat.pack(anchor="w")
        self.lbl_detall = ttk.Label(textos, text="", style="Secundari.TLabel", wraplength=360, justify="left")
        self.lbl_detall.pack(anchor="w")

        self.marc_progres = ttk.Frame(f)  # només es veu mentre es descarreguen els models
        self.barra = ttk.Progressbar(self.marc_progres, mode="determinate", maximum=1000)
        self.barra.pack(fill="x", pady=(12, 4))
        self.lbl_progres = ttk.Label(self.marc_progres, text="", style="Secundari.TLabel")
        self.lbl_progres.pack(anchor="w")

        self.marc_boto = ttk.Frame(f)
        self.marc_boto.pack(fill="x", pady=(14, 0))
        self.btn_actiu = ttk.Button(self.marc_boto, text="Activa", style="Accent.TButton", command=self.commuta)
        self.btn_actiu.pack(side="left", ipadx=18)
        self.lbl_comptadors = ttk.Label(self.marc_boto, text="", style="Secundari.TLabel")
        self.lbl_comptadors.pack(side="left", padx=12)
        self.lbl_dispositiu = ttk.Label(f, text="", style="Secundari.TLabel")
        self.lbl_dispositiu.pack(anchor="w", pady=(8, 0))

        ttk.Separator(f).pack(fill="x", pady=14)
        cap = ttk.Frame(f)
        cap.pack(fill="x", pady=(0, 6))
        ttk.Label(cap, text="Les teves cançons", style="Seccio.TLabel").pack(side="left")
        self.btn_esborra_totes = ttk.Button(cap, text="Esborra-les totes", command=self.esborra_totes)
        self.btn_esborra_totes.pack(side="right")
        self.lbl_total = ttk.Label(cap, text="", style="Secundari.TLabel")
        self.lbl_total.pack(side="right", padx=8)
        self.llista = LlistaFetes(f, self)
        self.llista.pack(fill="both", expand=True)

    def _formulari(self, f, benvinguda: bool) -> None:
        g = ttk.Frame(f)
        g.pack(fill="x")
        files = [("Token", ttk.Entry(g, textvariable=self.var_token, show="●")),
                 ("Servidor", ttk.Entry(g, textvariable=self.var_api)),
                 ("Nom de l'ordinador", ttk.Entry(g, textvariable=self.var_nom))]
        if not benvinguda:
            files.append(("Nuclis (0 = tots)", ttk.Spinbox(g, from_=0, to=64, textvariable=self.var_fils, width=6)))
        for i, (etiqueta, camp) in enumerate(files):
            ttk.Label(g, text=etiqueta).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=4)
            camp.grid(row=i, column=1, sticky="w" if isinstance(camp, ttk.Spinbox) else "ew", pady=4)
        g.columnconfigure(1, weight=1)
        if benvinguda:
            files[0][1].focus_set()
        if not self.var_nom.get():
            self.var_nom.set(windows_nom())

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
        self.lbl_estat.config(text=titol)
        self.lbl_detall.config(text=detall)
        self.activitat.mode = "aturat" if self.aturant else ("esperant" if fase == "engegant" else fase)

        if fase == "descarregant":
            self.btn_actiu.config(text="Descarregant models…", state="disabled")
        elif self.aturant and fase != "aturat":
            self.btn_actiu.config(text="Aturant…", state="disabled")
        else:
            self.btn_actiu.config(text="Desactiva" if fase != "aturat" else "Activa", state="normal")

        if fase == "descarregant":
            self.marc_progres.pack(fill="x", after=self.lbl_detall.master.master)
            d = self.descarrega
            self.barra.config(value=1000 * self.bytes_descarregats / max(d.total, 1))
            text = f"{_mida(self.bytes_descarregats)} de {_mida(d.total)}"
            velocitat = self._velocitat()
            if velocitat > 10_000:
                queden = (d.total - self.bytes_descarregats) / velocitat
                mbs = f"{velocitat / 1e6:.1f}".replace(".", ",")
                text += f" · {mbs} MB/s · queden uns {_durada(max(queden, 60))}"
            self.lbl_progres.config(text=text)
        else:
            self.marc_progres.pack_forget()

        e = self.estat
        parts = []
        if e.fetes or e.fallades:
            parts.append(f"Aquesta sessió: {e.fetes} fetes" + (f", {e.fallades} fallades" if e.fallades else ""))
        if e.fetes:
            parts.append(f"{e.temps_mitja_s / 60:.0f} min de mitjana")
        self.lbl_comptadors.config(text=" · ".join(parts))
        if self.perfil:
            self.lbl_dispositiu.config(text=f"Treballa amb: {self.perfil.device.upper()} — {self.perfil.nom}")

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
        if llista:
            self.lbl_total.config(text=f"{len(llista)} · {_mida(sum(f.mida for f in llista))}")
            self.btn_esborra_totes.pack(side="right")
        else:
            self.lbl_total.config(text="")
            self.btn_esborra_totes.pack_forget()

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
        self.prefs.api = self.var_api.get().strip()
        if token and set(token) != {"●"}:
            self.prefs.token = token
            self.var_token.set("●" * 8)
        self.prefs.nom_worker = self.var_nom.get().strip()
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
            self._construeix_principal()
            return
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
        fetes.desa(feina["id"], feina, res.analisi.model_dump_json(), wav, segons, self.prefs.desa_audio)
        self.cues.put(("fetes", None))

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
        client = Client(self.prefs.api, self.prefs.token, self.prefs.nom_worker or windows_nom(), perfil)
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
