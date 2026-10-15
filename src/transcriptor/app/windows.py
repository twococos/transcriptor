"""Utilitats específiques de Windows amb ctypes/winreg (cap dependència externa).

Fora de Windows, les funcions retornen valors neutres perquè l'app i els tests no petin.
"""

from __future__ import annotations

import base64
import ctypes
import logging
import sys
import threading
from ctypes import wintypes

log = logging.getLogger(__name__)

ES_WINDOWS = sys.platform == "win32"
CLAU_ARRENCADA = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOM_ARRENCADA = "Transcriptor"
NOM_MUTEX = r"Local\Transcriptor-app"
NOM_EVENT_MOSTRA = r"Local\Transcriptor-mostra"
_handles: list = []  # el mutex i l'event han de viure tant com el procés


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateEventW.restype = wintypes.HANDLE
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenEventW.restype = wintypes.HANDLE
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def instancia_unica(en_mostra) -> bool:
    """True si som l'única instància de l'app (per a aquest usuari). Si ja n'hi ha una, li demana que
    mostri la finestra i retorna False. A la primera, `en_mostra()` es crida (des d'un altre fil) cada
    cop que una instància nova ho demana."""
    if not ES_WINDOWS:
        return True
    k = _kernel32()
    mutex = k.CreateMutexW(None, False, NOM_MUTEX)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        event = k.OpenEventW(0x0002, False, NOM_EVENT_MOSTRA)  # EVENT_MODIFY_STATE
        if event:
            k.SetEvent(event)
            k.CloseHandle(event)
        k.CloseHandle(mutex)
        return False
    event = k.CreateEventW(None, False, False, NOM_EVENT_MOSTRA)  # reinici automàtic
    _handles.extend([mutex, event])

    def espera() -> None:
        while k.WaitForSingleObject(event, 0xFFFFFFFF) == 0:  # INFINITE → WAIT_OBJECT_0
            en_mostra()

    threading.Thread(target=espera, daemon=True, name="instancia-unica").start()
    return True


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
