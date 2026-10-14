"""Worker pull: demana feines a l'API del canconer, les processa i en retorna el resultat.

Protocol proposat a docs/api_worker.md (pendent de validar a la Fase 6). Només fa connexions de
sortida, així funciona igual al PC, al servidor, a casa d'un amic o en una GPU llogada.

Bucle: claim → (heartbeat en paral·lel) pipeline → result | fail → esborrar l'àudio → repetir.
Aturada neta: si es demana parar a mitja feina, l'allibera (fail amb released=true) perquè torni
a la cua.
"""

from __future__ import annotations

import logging
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from . import __version__
from .cache import Cache
from .config import Config
from .device import Perfil, detecta
from .pipeline import Entrada, executa
from .stages.fetch import id_canco

log = logging.getLogger(__name__)

ESPERA_MIN_S = 30
ESPERA_MAX_S = 300


class VersioMassaAntiga(Exception):
    pass


class FeinaPerduda(Exception):
    """El servidor ja no ens reconeix la feina (lease caducat o reassignada)."""


@dataclass
class EstatWorker:
    """Estat observable (per a l'app d'escriptori)."""
    actiu: bool = False
    feina_actual: str | None = None
    fetes: int = 0
    fallades: int = 0
    temps_mitja_s: float = 0.0
    ultim_error: str | None = None
    missatge: str = "Aturat"
    historial: list[dict] = field(default_factory=list)


class Client:
    def __init__(self, api: str, token: str, nom: str, perfil: Perfil, timeout: float = 30):
        self.api = api.rstrip("/")
        self.sessio = requests.Session()
        self.sessio.headers.update({"Authorization": f"Bearer {token}",
                                    "User-Agent": f"transcriptor-worker/{__version__}"})
        self.nom = nom
        self.perfil = perfil
        self.timeout = timeout

    def _post(self, cami: str, dades: dict) -> requests.Response:
        r = self.sessio.post(f"{self.api}/api/transcriber{cami}", json=dades, timeout=self.timeout)
        if r.status_code == 426:
            raise VersioMassaAntiga(r.json().get("min_version", "?"))
        if r.status_code == 401:
            raise PermissionError("Token rebutjat (revocat o incorrecte)")
        return r

    def claim(self) -> dict | None:
        r = self._post("/claim", {
            "worker": self.nom, "app_version": __version__,
            "device": {"type": self.perfil.device, "name": self.perfil.nom, "vram_gb": self.perfil.vram_gb},
        })
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()["job"]

    def heartbeat(self, id_feina: int) -> None:
        r = self._post(f"/jobs/{id_feina}/heartbeat", {})
        if r.status_code in (404, 409, 410):
            raise FeinaPerduda(id_feina)
        r.raise_for_status()

    def resultat(self, id_feina: int, proposta: dict, analisi: dict) -> None:
        self._post(f"/jobs/{id_feina}/result", {"proposal": proposta, "analysis": analisi}).raise_for_status()

    def falla(self, id_feina: int, error: str, alliberada: bool = False) -> None:
        try:
            self._post(f"/jobs/{id_feina}/fail", {"error": error[:2000], "released": alliberada})
        except requests.RequestException as e:
            log.warning("No s'ha pogut notificar la fallada: %s", e)


class Worker:
    def __init__(self, client: Client, cfg: Config, perfil: Perfil,
                 en_canvi: Callable[[EstatWorker], None] | None = None):
        self.client = client
        self.cfg = cfg
        self.perfil = perfil
        self.estat = EstatWorker()
        self.atura = threading.Event()
        self.en_canvi = en_canvi or (lambda _e: None)

    def _avisa(self, missatge: str) -> None:
        self.estat.missatge = missatge
        log.info(missatge)
        self.en_canvi(self.estat)

    def _batec(self, id_feina: int, lease_s: float, perduda: threading.Event, fi: threading.Event) -> None:
        while not fi.wait(max(lease_s / 3, 5)):
            try:
                self.client.heartbeat(id_feina)
            except FeinaPerduda:
                perduda.set()
                return
            except requests.RequestException as e:
                log.warning("Heartbeat fallit (es reintentarà): %s", e)

    def processa(self, feina: dict) -> None:
        id_feina = feina["id"]
        self.estat.feina_actual = f"{feina.get('title') or ''} — {feina.get('artist') or ''}".strip(" —")
        self._avisa(f"Processant: {self.estat.feina_actual or feina['source_url']}")
        perduda, fi = threading.Event(), threading.Event()
        batec = threading.Thread(target=self._batec, daemon=True,
                                 args=(id_feina, float(feina.get("lease_seconds", 600)), perduda, fi))
        batec.start()
        inici = time.perf_counter()
        cache = Cache(id_canco(feina["source_url"]))
        try:
            res = executa(Entrada(font=feina["source_url"], titol=feina.get("title"), artista=feina.get("artist"),
                                  idioma=feina.get("language"), text_usuari=feina.get("lyrics_text"),
                                  content_bd=feina.get("song_content")),
                          self.cfg, self.perfil, cache)
            if perduda.is_set():
                raise FeinaPerduda(id_feina)
            if self.atura.is_set():
                raise InterruptedError
            self.client.resultat(id_feina, res.proposta.model_dump(), res.analisi.model_dump())
            durada = time.perf_counter() - inici
            self.estat.fetes += 1
            self.estat.temps_mitja_s += (durada - self.estat.temps_mitja_s) / self.estat.fetes
            self.estat.historial.append({"titol": self.estat.feina_actual, "segons": round(durada), "ok": True})
        except InterruptedError:
            self.client.falla(id_feina, "Worker aturat", alliberada=True)
        except KeyboardInterrupt:
            self.client.falla(id_feina, "Worker aturat (Ctrl+C)", alliberada=True)
            raise
        except FeinaPerduda:
            log.warning("La feina %s ja no és nostra (lease caducat)", id_feina)
        except Exception as e:  # noqa: BLE001 — qualsevol error es reporta al servidor
            log.exception("Feina %s fallida", id_feina)
            self.estat.fallades += 1
            self.estat.ultim_error = str(e)[:300]
            self.estat.historial.append({"titol": self.estat.feina_actual, "error": str(e)[:300], "ok": False})
            self.client.falla(id_feina, f"{type(e).__name__}: {e}")
        finally:
            fi.set()
            cache.esborra_audio()  # no s'emmagatzema àudio de YouTube
            self.estat.feina_actual = None
            self.estat.historial = self.estat.historial[-50:]
            self.en_canvi(self.estat)

    def bucle(self, una: bool = False) -> None:
        self.estat.actiu = True
        espera = ESPERA_MIN_S
        try:
            while not self.atura.is_set():
                try:
                    feina = self.client.claim()
                except (VersioMassaAntiga, PermissionError):
                    raise
                except requests.RequestException as e:
                    self._avisa(f"Sense connexió amb l'API ({e.__class__.__name__}); reintent en {espera} s")
                    self.atura.wait(espera)
                    espera = min(espera * 2, ESPERA_MAX_S)
                    continue
                if feina is None:
                    self._avisa("Cua buida; esperant feina")
                    if una:
                        return
                    self.atura.wait(espera)
                    espera = min(espera * 2, ESPERA_MAX_S)
                    continue
                espera = ESPERA_MIN_S
                self.processa(feina)
                if una:
                    return
        finally:
            self.estat.actiu = False
            self._avisa("Aturat")


def executa_worker(args) -> int:
    perfil = detecta(args.device)
    client = Client(args.api, args.token, args.nom or platform.node(), perfil)
    worker = Worker(client, Config.carrega(args.config), perfil)
    try:
        worker.bucle(una=args.una)
    except VersioMassaAntiga as e:
        log.error("Aquest worker és massa antic: l'API demana la versió %s o superior", e)
        return 3
    except PermissionError as e:
        log.error("%s", e)
        return 2
    except KeyboardInterrupt:
        worker.atura.set()
    return 0
