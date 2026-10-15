"""Prova manual de l'app d'escriptori contra un servidor simulat.

Ús: python proves/prova_app.py <url_youtube> <captura.png>
Fa servir un APPDATA temporal (no toca la configuració real), activa el worker, espera que el
servidor simulat rebi el resultat, fa una captura de la finestra i surt.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="tx-app-")
sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))

from test_worker import Servidor  # noqa: E402

from transcriptor.app import __main__ as app_mod  # noqa: E402
from transcriptor.app.settings import Preferencies  # noqa: E402

url, captura = sys.argv[1], sys.argv[2]
servidor = Servidor([{"id": 1, "source_url": url, "title": "L'estaca", "artist": "Lluís Llach",
                      "lease_seconds": 60}])
prefs = Preferencies(api=servidor.url, nom_worker="prova", nomes_inactiu=False)
prefs.token = "secret"
prefs.desa()

app_mod._configura_logs()
app = app_mod.App()
inici = time.time()


def vigila() -> None:
    if 1 in servidor.resultats or 1 in servidor.fallades or time.time() - inici > 900:
        app.arrel.after(1500, captura_i_surt)
        return
    app.arrel.after(1000, vigila)


def captura_i_surt() -> None:
    from PIL import ImageGrab

    app.arrel.update()
    x, y = app.arrel.winfo_rootx(), app.arrel.winfo_rooty()
    w, h = app.arrel.winfo_width(), app.arrel.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(captura)
    print("resultat:", "OK" if 1 in servidor.resultats else servidor.fallades.get(1))
    print("peticions:", [p for p, _ in servidor.peticions])
    if 1 in servidor.resultats:
        print("clau:", servidor.resultats[1]["proposal"]["key"], "| línies:",
              servidor.resultats[1]["proposal"]["content"].count("\n") + 1)
    app.surt()


app.arrel.after(500, app.activa)
app.arrel.after(1000, vigila)
app.executa()
servidor.tanca()
print(f"temps: {time.time() - inici:.0f} s; registre: {Path(os.environ['APPDATA']) / 'Transcriptor'}")
