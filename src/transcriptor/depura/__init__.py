"""Depurador i visor del transcriptor (`tx depura`): cada pas del postprocés de qualsevol cançó.

- origens.py: d'on surten les cançons (banc, caches locals, fitxers) i les seves dades.
- genera.py: la traça d'una cançó (postprocés pas a pas, sense tabs i la referència). El worker
  en fa servir `completa` per pujar la traça al canconer amb cada resultat.
- servidor.py: el servidor local i les rutes de l'API.
- depura.html: la pàgina (reproductor amb YouTube, línia de temps per etapes, content costat a
  costat…). La mateixa pàgina, copiada a public/depurador/ del canconer, és el depurador de l'admin.

Vegeu docs/depurador.md.
"""


def serveix(port: int = 8766, obre: bool = True, que: str | None = None) -> int:
    from .servidor import serveix as _serveix

    return _serveix(port, obre, que)
