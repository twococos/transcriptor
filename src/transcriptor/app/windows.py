"""Utilitats específiques de Windows amb ctypes/winreg (cap dependència externa).

Fora de Windows, les funcions retornen valors neutres perquè l'app i els tests no petin.
"""

from __future__ import annotations

import base64
import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

ES_WINDOWS = sys.platform == "win32"
CLAU_ARRENCADA = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOM_ARRENCADA = "Transcriptor"


def segons_inactiu() -> float:
    """Segons des de l'última interacció amb el teclat o el ratolí."""
    if not ES_WINDOWS:
        return float("inf")

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    ara = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((ara - info.dwTime) & 0xFFFFFFFF) / 1000.0


def prioritat_baixa() -> None:
    """Prioritat "per sota del normal": el worker no alenteix el que faci l'usuari."""
    if not ES_WINDOWS:
        return
    BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)


def tema_fosc() -> bool:
    """Si l'usuari té les aplicacions de Windows en mode fosc."""
    if not ES_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def arrencada_activa() -> bool:
    if not ES_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAU_ARRENCADA) as k:
            winreg.QueryValueEx(k, NOM_ARRENCADA)
            return True
    except OSError:
        return False


def configura_arrencada(activa: bool, ordre: str) -> None:
    """Afegeix o treu l'app de l'arrencada de Windows (només per a l'usuari actual)."""
    if not ES_WINDOWS:
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAU_ARRENCADA, 0, winreg.KEY_SET_VALUE) as k:
        if activa:
            winreg.SetValueEx(k, NOM_ARRENCADA, 0, winreg.REG_SZ, ordre)
        else:
            try:
                winreg.DeleteValue(k, NOM_ARRENCADA)
            except FileNotFoundError:
                pass


class _DATA_BLOB(ctypes.Structure):  # noqa: N801 — nom de l'API de Windows
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dades: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(dades, len(dades))
    return _DATA_BLOB(len(dades), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(dades: bytes, xifra: bool) -> bytes:
    entrada, sortida = _blob(dades), _DATA_BLOB()
    funcio = ctypes.windll.crypt32.CryptProtectData if xifra else ctypes.windll.crypt32.CryptUnprotectData
    if not funcio(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(sortida)):
        raise OSError("DPAPI ha fallat")
    try:
        return ctypes.string_at(sortida.pbData, sortida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(sortida.pbData)


def protegeix(secret: str) -> str:
    """Xifra amb DPAPI (només l'usuari de Windows actual el pot desxifrar). Fora de Windows, base64."""
    dades = secret.encode()
    if ES_WINDOWS:
        return "dpapi:" + base64.b64encode(_dpapi(dades, True)).decode()
    return "b64:" + base64.b64encode(dades).decode()


def desprotegeix(valor: str) -> str:
    if not valor:
        return ""
    tipus, _, dades = valor.partition(":")
    crues = base64.b64decode(dades)
    if tipus == "dpapi":
        return _dpapi(crues, False).decode()
    return crues.decode()
