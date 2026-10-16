"""Pestanya "Classificacions": els workers que més cançons han transcrit, més temps hi han dedicat i
més ràpids són (vegeu GET /api/transcriber/leaderboard a docs/api_worker.md).

L'última resposta es desa al disc per poder-la mostrar sense connexió.
"""

from __future__ import annotations

import json
import logging
import time
from tkinter import ttk
from typing import Callable

from .grafics import copa
from .settings import dir_app

log = logging.getLogger(__name__)

CLAUS = ("songs", "total_time", "speed")
TITOLS = {"songs": "Cançons transcrites", "total_time": "Temps total transcrivint", "speed": "Més ràpid"}
EN_QUE = {"songs": "en cançons transcrites", "total_time": "en temps transcrivint", "speed": "en rapidesa"}
PERIODES = {"all": "Sempre", "month": "Aquest mes"}


def _fitxer():
    return dir_app() / "classificacions.json"


def carrega_desades() -> tuple[dict | None, float | None]:
    try:
        d = json.loads(_fitxer().read_text(encoding="utf-8"))
        return d["dades"], d["rebut"]
    except (OSError, ValueError, KeyError):
        return None, None


def desa(dades: dict) -> None:
    try:
        _fitxer().write_text(json.dumps({"rebut": time.time(), "dades": dades}, ensure_ascii=False),
                             encoding="utf-8")
    except OSError:
        log.warning("No s'han pogut desar les classificacions", exc_info=True)


def ordinal(n: int) -> str:
    return {1: "1r", 2: "2n", 3: "3r", 4: "4t"}.get(n, f"{n}è")


def valor(clau: str, v: float | None) -> str:
    if v is None:
        return "—"
    if clau == "songs":
        return f"{int(v)} {'cançó' if v == 1 else 'cançons'}"
    s = int(round(v))
    if clau == "speed":
        return f"{s // 60}:{s % 60:02d} per minut de cançó"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def _posicions(dades: dict | None) -> dict[tuple[str, str], int]:
    """{(període, classificació): posició} del worker propi, només on en té."""
    out = {}
    for periode, taules in ((dades or {}).get("periods") or {}).items():
        for clau in CLAUS:
            me = (taules.get(clau) or {}).get("me") or {}
            if me.get("rank"):
                out[(periode, clau)] = me["rank"]
    return out


def destacades(dades: dict | None) -> list[tuple[int, str]]:
    """Podis del worker propi, de millor a pitjor: [(posició, "Ets 1r en cançons transcrites")]."""
    podis = [(rank, f"Ets {ordinal(rank)} {EN_QUE[clau]}" + (" aquest mes" if periode == "month" else ""))
             for (periode, clau), rank in _posicions(dades).items() if rank <= 3]
    # A igual posició, primer la de sempre
    return sorted(podis, key=lambda p: (p[0], "aquest mes" in p[1]))


def millores(abans: dict | None, ara: dict | None) -> list[str]:
    """Podis nous o millorats respecte de la resposta anterior (per avisar-ne)."""
    if not abans:
        return []
    vells = _posicions(abans)
    return [f"Has pujat al {ordinal(rank)} lloc {EN_QUE[clau]}" + (" aquest mes" if periode == "month" else "")
            for (periode, clau), rank in _posicions(ara).items()
            if rank <= 3 and rank < vells.get((periode, clau), 99)]


def _fa(rebut: float) -> str:
    s = time.time() - rebut
    if s < 90:
        return "ara mateix"
    if s < 3600:
        return f"fa {int(s // 60)} min"
    if s < 86400:
        return f"fa {int(s // 3600)} h"
    return f"fa {int(s // 86400)} dies"


class PestanyaClassificacions(ttk.Frame):
    def __init__(self, pare, en_actualitza: Callable[[], None]):
        super().__init__(pare, padding=(14, 14))
        self.periode = "all"
        self.dades: dict | None = None
        self.rebut: float | None = None
        self.error: str | None = None
        self.imatges: dict[int, object] = {}

        dalt = ttk.Frame(self)
        dalt.pack(fill="x", pady=(0, 10))
        self.botons: dict[str, ttk.Button] = {}
        for clau, text in PERIODES.items():
            b = ttk.Button(dalt, text=text, command=lambda c=clau: self._tria(c))
            b.pack(side="left", padx=(0, 6))
            self.botons[clau] = b
        ttk.Button(dalt, text="Actualitza", command=en_actualitza).pack(side="right")
        self.lbl_rebut = ttk.Label(dalt, text="", style="Secundari.TLabel")
        self.lbl_rebut.pack(side="right", padx=8)

        self.cos = ttk.Frame(self)
        self.cos.pack(fill="both", expand=True)
        self._tria("all")

    def _copa(self, rank: int):
        if rank not in self.imatges:
            from PIL import ImageTk

            self.imatges[rank] = ImageTk.PhotoImage(copa(rank, 20))
        return self.imatges[rank]

    def _tria(self, periode: str) -> None:
        self.periode = periode
        for clau, b in self.botons.items():
            b.config(style="Accent.TButton" if clau == periode else "TButton")
        self._dibuixa()

    def mostra(self, dades: dict | None, rebut: float | None, error: str | None = None) -> None:
        if dades is not None:
            self.dades, self.rebut = dades, rebut
        self.error = error
        self._dibuixa()

    def refresca_rebut(self) -> None:
        text = f"Actualitzat {_fa(self.rebut)}" if self.rebut else ""
        if self.error:
            text = f"{self.error}" + (f" · dades {_fa(self.rebut)}" if self.rebut else "")
        self.lbl_rebut.config(text=text)

    def _dibuixa(self) -> None:
        for w in self.cos.winfo_children():
            w.destroy()
        self.refresca_rebut()
        if not self.dades:
            ttk.Label(self.cos, style="Secundari.TLabel", wraplength=440, justify="left",
                      text="Encara no s'han pogut carregar les classificacions. Quan l'app es connecti al "
                           "servidor, aquí veuràs qui ha transcrit més cançons, qui hi ha dedicat més temps "
                           "i qui és més ràpid.").pack(anchor="w", pady=8)
            return
        taules = (self.dades.get("periods") or {}).get(self.periode) or {}
        for i, clau in enumerate(CLAUS):
            if i:
                ttk.Separator(self.cos).pack(fill="x", pady=10)
            ttk.Label(self.cos, text=TITOLS[clau], style="Seccio.TLabel").pack(anchor="w", pady=(0, 4))
            self._taula(clau, taules.get(clau) or {})

    def _fila(self, posicio: str | int, nom: str, text_valor: str, propi: bool) -> None:
        f = ttk.Frame(self.cos)
        f.pack(fill="x", pady=1)
        if isinstance(posicio, int) and posicio <= 3:
            ttk.Label(f, image=self._copa(posicio), width=4).pack(side="left")
        else:
            ttk.Label(f, text=str(posicio), width=4, anchor="center", style="Secundari.TLabel").pack(side="left")
        estil = "Accent.TLabel" if propi else "TLabel"
        ttk.Label(f, text=text_valor, style=estil).pack(side="right")
        ttk.Label(f, text=nom if len(nom) <= 30 else nom[:29] + "…", style=estil).pack(side="left", padx=(4, 0))

    def _taula(self, clau: str, taula: dict) -> None:
        top = taula.get("top") or []
        me = taula.get("me")
        nom_propi = ((self.dades or {}).get("me") or {}).get("name") or "Tu"
        if not top:
            ttk.Label(self.cos, text="Encara no hi ha ningú.", style="Secundari.TLabel").pack(anchor="w")
        for e in top:
            self._fila(e["rank"], e["name"], valor(clau, e["value"]), e.get("me", False))
        en_top = any(e.get("me") for e in top)
        if me and not en_top:
            if me.get("rank"):
                ttk.Label(self.cos, text="···", style="Secundari.TLabel").pack(anchor="w", padx=(12, 0))
                self._fila(ordinal(me["rank"]), nom_propi, valor(clau, me.get("value")), True)
            elif clau == "speed":
                falten = max(int(self.dades.get("min_songs_speed", 5)) - int(me.get("songs") or 0), 1)
                ttk.Label(self.cos, style="Secundari.TLabel",
                          text=("Et falta 1 cançó per entrar-hi." if falten == 1
                                else f"Et falten {falten} cançons per entrar-hi.")
                          ).pack(anchor="w", pady=(2, 0))
        elif not me and clau == "songs" and top:
            ttk.Label(self.cos, text="Encara no hi surts: transcriu la primera cançó!",
                      style="Secundari.TLabel").pack(anchor="w", pady=(2, 0))
