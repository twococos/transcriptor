"""Depurador i visor del transcriptor (`tx depura`): cada pas del postprocés de qualsevol cançó.

- origens.py: d'on surten les cançons (banc, canconer, caches locals, fitxers) i les seves dades.
- web.py: el client de l'API del canconer.
- genera.py: la traça d'una cançó (postprocés pas a pas, sense tabs i la referència).
- servidor.py: el servidor local i les rutes de l'API.
- depura.html: la pàgina (reproductor amb YouTube, línia de temps per etapes, content costat a costat…).

Vegeu docs/depurador.md.
"""


def serveix(port: int = 8766, obre: bool = True, que: str | None = None, api: str | None = None,
            token: str | None = None) -> int:
    from .servidor import serveix as _serveix

    return _serveix(port, obre, que, api, token)
