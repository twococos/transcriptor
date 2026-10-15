"""App d'escriptori del worker: icona a la barra de tasques + finestra d'estat i configuració.

    pythonw -m transcriptor.app

- La icona (pystray) té un menú: activar/desactivar, obrir la finestra, sortir.
- La finestra (tkinter, ve amb Python) mostra l'estat i permet enganxar el token, triar
  "només quan l'ordinador estigui inactiu", límit de nuclis i arrencar amb Windows.
- El worker corre en un fil; desactivar-lo l'atura netament (allibera la feina en curs).
- El procés corre amb prioritat baixa perquè no alenteixi l'ordinador.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import replace
from tkinter import messagebox, ttk

from .. import __version__
from ..config import Config
from ..device import detecta
from ..worker import Client, EstatWorker, VersioMassaAntiga, Worker
from . import windows
from .settings import Preferencies, dir_app

log = logging.getLogger("transcriptor.app")


def _configura_logs() -> None:
    fitxer = dir_app() / "transcriptor.log"
    gestor = logging.handlers.RotatingFileHandler(fitxer, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    gestor.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[gestor])
    for soroll in ("httpx", "httpx2", "huggingface_hub", "urllib3", "faster_whisper", "numba"):
        logging.getLogger(soroll).setLevel(logging.WARNING)


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


class App:
    def __init__(self) -> None:
        self.prefs = Preferencies.carrega()
        self.cues: queue.Queue = queue.Queue()  # actualitzacions d'estat des del fil del worker
        self.worker: Worker | None = None
        self.fil: threading.Thread | None = None
        self.estat = EstatWorker()
        self.perfil = None
        self.icona = None

        self.arrel = tk.Tk()
        self.arrel.title(f"Transcriptor {__version__}")
        self.arrel.geometry("460x520")
        self.arrel.protocol("WM_DELETE_WINDOW", self.amaga)
        self._construeix()
        self.arrel.after(300, self._processa_cua)

    # ── Interfície ──────────────────────────────────────────────────────────
    def _construeix(self) -> None:
        f = ttk.Frame(self.arrel, padding=12)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Estat", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.lbl_estat = ttk.Label(f, text="Aturat", wraplength=420)
        self.lbl_estat.pack(anchor="w", pady=(2, 0))
        self.lbl_dispositiu = ttk.Label(f, text="", foreground="#666")
        self.lbl_dispositiu.pack(anchor="w")
        self.lbl_comptadors = ttk.Label(f, text="")
        self.lbl_comptadors.pack(anchor="w", pady=(0, 8))
        self.btn_actiu = ttk.Button(f, text="Activa", command=self.commuta)
        self.btn_actiu.pack(anchor="w", pady=(0, 12))

        ttk.Separator(f).pack(fill="x", pady=4)
        ttk.Label(f, text="Configuració", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(4, 2))

        g = ttk.Frame(f)
        g.pack(fill="x")
        ttk.Label(g, text="Servidor").grid(row=0, column=0, sticky="w")
        self.var_api = tk.StringVar(value=self.prefs.api)
        ttk.Entry(g, textvariable=self.var_api, width=40).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(g, text="Token").grid(row=1, column=0, sticky="w")
        self.var_token = tk.StringVar(value="●" * 8 if self.prefs.token_protegit else "")
        self.ent_token = ttk.Entry(g, textvariable=self.var_token, width=40, show="●")
        self.ent_token.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(g, text="Nom").grid(row=2, column=0, sticky="w")
        self.var_nom = tk.StringVar(value=self.prefs.nom_worker)
        ttk.Entry(g, textvariable=self.var_nom, width=40).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Label(g, text="Nuclis (0 = auto)").grid(row=3, column=0, sticky="w")
        self.var_fils = tk.IntVar(value=self.prefs.max_fils)
        ttk.Spinbox(g, from_=0, to=64, textvariable=self.var_fils, width=6).grid(row=3, column=1, sticky="w")
        g.columnconfigure(1, weight=1)

        self.var_inactiu = tk.BooleanVar(value=self.prefs.nomes_inactiu)
        ttk.Checkbutton(f, text="Només quan no faig servir l'ordinador (5 min sense teclat ni ratolí)",
                        variable=self.var_inactiu).pack(anchor="w", pady=(8, 0))
        self.var_arrencada = tk.BooleanVar(value=windows.arrencada_activa())
        ttk.Checkbutton(f, text="Arrenca amb Windows", variable=self.var_arrencada).pack(anchor="w")
        self.var_auto = tk.BooleanVar(value=self.prefs.actiu)
        ttk.Checkbutton(f, text="Activa el worker en obrir l'app", variable=self.var_auto).pack(anchor="w")

        b = ttk.Frame(f)
        b.pack(fill="x", pady=10)
        ttk.Button(b, text="Desa", command=self.desa).pack(side="left")
        ttk.Button(b, text="Obre el registre", command=self.obre_registre).pack(side="left", padx=6)

        ttk.Separator(f).pack(fill="x", pady=4)
        ttk.Label(f, text="Últimes cançons", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.llista = tk.Listbox(f, height=6)
        self.llista.pack(fill="both", expand=True)

    def _refresca(self) -> None:
        e = self.estat
        self.lbl_estat.config(text=e.missatge + (f"\nÚltim error: {e.ultim_error}" if e.ultim_error else ""))
        self.lbl_comptadors.config(text=f"Fetes: {e.fetes} · Fallades: {e.fallades}"
                                        + (f" · Mitjana: {e.temps_mitja_s / 60:.1f} min" if e.fetes else ""))
        self.btn_actiu.config(text="Desactiva" if e.actiu else "Activa")
        if self.perfil:
            self.lbl_dispositiu.config(text=f"Dispositiu: {self.perfil.device.upper()} — {self.perfil.nom}")
        self.llista.delete(0, "end")
        for h in reversed(e.historial[-20:]):
            self.llista.insert("end", f"{'✓' if h['ok'] else '✗'} {h['titol']}"
                                      + (f" ({h['segons'] // 60} min)" if h.get("segons") else ""))
        if self.icona:
            self.icona.icon = _icona(e.actiu)
            self.icona.title = f"Transcriptor — {e.missatge}"

    def _processa_cua(self) -> None:
        try:
            while True:
                tipus, dades = self.cues.get_nowait()
                if tipus == "estat":
                    self.estat = dades
                elif tipus == "error":
                    messagebox.showerror("Transcriptor", dades)
                self._refresca()
        except queue.Empty:
            pass
        self.arrel.after(500, self._processa_cua)

    # ── Accions ─────────────────────────────────────────────────────────────
    def desa(self) -> None:
        self.prefs.api = self.var_api.get().strip()
        if self.var_token.get() and set(self.var_token.get()) != {"●"}:
            self.prefs.token = self.var_token.get()
            self.var_token.set("●" * 8)
        self.prefs.nom_worker = self.var_nom.get().strip()
        self.prefs.max_fils = int(self.var_fils.get() or 0)
        self.prefs.nomes_inactiu = self.var_inactiu.get()
        self.prefs.actiu = self.var_auto.get()
        self.prefs.arrencar_amb_windows = self.var_arrencada.get()
        ordre = f'"{sys.executable.replace("python.exe", "pythonw.exe")}" -m transcriptor.app'
        windows.configura_arrencada(self.prefs.arrencar_amb_windows, ordre)
        self.prefs.desa()

    def obre_registre(self) -> None:
        webbrowser.open((dir_app() / "transcriptor.log").as_uri())

    def _pot_treballar(self) -> str | None:
        if self.prefs.nomes_inactiu:
            inactiu = windows.segons_inactiu()
            if inactiu < self.prefs.minuts_inactiu * 60:
                return "l'ordinador s'està fent servir"
        return None

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
                             pot_treballar=self._pot_treballar)

        def corre() -> None:
            try:
                self._prepara_models()
                self.worker.bucle()
            except VersioMassaAntiga as e:
                self.cues.put(("error", f"Cal actualitzar el Transcriptor (versió mínima {e})."))
            except PermissionError as e:
                self.cues.put(("error", f"El servidor ha rebutjat el token: {e}"))
            except Exception as e:  # noqa: BLE001
                log.exception("Error del worker")
                self.cues.put(("error", f"Error inesperat: {e}"))

        self.fil = threading.Thread(target=corre, daemon=True, name="worker")
        self.fil.start()

    def _prepara_models(self) -> None:
        from ..models import prepara

        def progres(missatge: str, i: int, n: int) -> None:
            self.estat.missatge = f"Preparant models ({i}/{n}): {missatge}"
            self.cues.put(("estat", self.estat))

        prepara(self.perfil, Config(), progres)

    def desactiva(self) -> None:
        if self.worker:
            self.worker.atura.set()
            self.estat.missatge = "Aturant (acabant d'alliberar la feina)..."
            self._refresca()

    def commuta(self) -> None:
        if self.fil and self.fil.is_alive():
            self.desactiva()
        else:
            self.activa()

    def mostra(self) -> None:
        self.arrel.after(0, lambda: (self.arrel.deiconify(), self.arrel.lift()))

    def amaga(self) -> None:
        self.arrel.withdraw()

    def surt(self) -> None:
        self.desactiva()
        if self.fil:
            self.fil.join(timeout=10)
        if self.icona:
            self.icona.stop()
        self.arrel.after(0, self.arrel.destroy)

    def executa(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Obre", lambda: self.mostra(), default=True),
            pystray.MenuItem(lambda _i: "Desactiva" if self.estat.actiu else "Activa",
                             lambda: self.arrel.after(0, self.commuta)),
            pystray.MenuItem("Surt", lambda: self.arrel.after(0, self.surt)),
        )
        self.icona = pystray.Icon("transcriptor", _icona(False), "Transcriptor", menu)
        self.icona.run_detached()
        if self.prefs.actiu and self.prefs.token_protegit:
            self.arrel.withdraw()
            self.activa()
        self._refresca()
        self.arrel.mainloop()


def windows_nom() -> str:
    import platform

    return platform.node() or "worker"


def main() -> None:
    # Models, cache i àudio temporal fora del directori d'instal·lació
    base = os.environ.get("LOCALAPPDATA") or str(dir_app())
    os.environ.setdefault("TX_HOME", os.path.join(base, "Transcriptor", "dades"))
    _configura_logs()
    windows.prioritat_baixa()
    App().executa()


if __name__ == "__main__":
    main()
