"""Client del canconer per al depurador: llista les cançons amb anàlisi i en baixa les dades.

Fa servir l'API dels workers (vegeu docs/depurador.md), amb el token d'un worker:
`tx depura --token` (o les variables TX_API / TX_TOKEN) o, si no, el de l'app d'escriptori.
"""

from __future__ import annotations

import os

import requests

from .. import __version__

API_PER_DEFECTE = "https://guitarreo.cat"


class ErrorWeb(Exception):
    pass


def credencials() -> tuple[str, str | None]:
    """(URL del canconer, token). El token de l'app només es pot llegir amb el mateix usuari de Windows."""
    api, token = os.environ.get("TX_API"), os.environ.get("TX_TOKEN")
    if not token:
        try:
            from ..app.settings import Preferencies

            prefs = Preferencies.carrega()
            token = prefs.token or None
            api = api or prefs.api
        except Exception:  # noqa: BLE001 — sense app (Linux) o sense configuració: no hi ha token
            token = None
    return (api or API_PER_DEFECTE).rstrip("/"), token


def _get(cami: str, **params) -> dict:
    api, token = credencials()
    if not token:
        raise ErrorWeb("Sense token de worker: passa'l amb `tx depura --token tx_…`, a TX_TOKEN o configura l'app")
    try:
        r = requests.get(f"{api}/api/transcriber{cami}", params=params or None, timeout=60,
                         headers={"Authorization": f"Bearer {token}", "User-Agent": f"transcriptor-worker/{__version__}"})
    except requests.RequestException as e:
        raise ErrorWeb(f"No es pot connectar amb {api}: {e}") from e
    if r.status_code == 401:
        raise ErrorWeb("El canconer ha rebutjat el token (revocat o incorrecte)")
    if r.status_code == 404 and cami == "/songs":
        raise ErrorWeb(f"{api} encara no té l'API del depurador: cal desplegar la web")
    if r.status_code == 404:
        raise ErrorWeb(r.json().get("error", "No trobat") if r.headers.get("content-type", "").startswith(
            "application/json") else "No trobat")
    if not r.ok:
        raise ErrorWeb(f"El canconer ha respost {r.status_code}")
    return r.json()


def llista(q: str = "", limit: int = 200) -> list[dict]:
    """Cançons amb anàlisi: [{id, title, artist, youtube_url, app_version, has_raw, analyzed_at}]."""
    return _get("/songs", q=q, limit=limit)["songs"]


def canco(id_canco: int) -> dict:
    """El que rebria un worker en una feina `update` d'aquesta cançó, més `transcriber_content`."""
    return _get(f"/songs/{id_canco}")
