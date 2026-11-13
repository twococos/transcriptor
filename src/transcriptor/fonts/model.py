"""Format comú de les tabs d'acords.

Cada lloc (llocs/*.py) converteix la seva pàgina al format `content` del canconer: una línia per
línia de la tab, `<sec>Nom</sec>` sol a la seva línia per a les seccions i `<ch>X</ch>` enmig del
text a la columna on va l'acord. És el mateix que fan els importadors de la web
(src/lib/importers/*.ts), així el content de la BD i les tabs es llegeixen igual (normalitza.py).
Els acords es deixen tal com els escriu la pàgina (bemolls, solfeig...): els normalitza normalitza.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Candidat:
    """Un resultat de la cerca d'un lloc, abans de baixar-lo."""
    lloc: str
    url: str
    titol: str
    artista: str
    valoracio: float | None = None  # 0–5
    vots: int | None = None
    versio: int | None = None
    extra: dict = field(default_factory=dict)  # dades del lloc per a `baixa` (p. ex. id intern)


@dataclass
class TabCrua:
    """Una tab baixada, en format content del canconer (acords encara sense normalitzar)."""
    lloc: str
    url: str
    titol: str
    artista: str
    content: str
    capo: int = 0
    to: str | None = None  # tonalitat que declara la pàgina, si n'hi ha
    valoracio: float | None = None
    vots: int | None = None
    versio: int | None = None
    manual: bool = False  # afegida a mà des de l'admin

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: dict) -> "TabCrua":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class AcordTab:
    col: int  # columna dins `LiniaTab.text`
    escrit: str  # notació del projecte: sostinguts, sufix de CHORD_MODIFIERS, baix opcional ("G/B")
    classe: str  # etiqueta del vocabulari de BTC (nivell sevenths) per comparar: "G", "Am7", "Bdim"...


@dataclass
class LiniaTab:
    text: str  # lletra (buida en una línia només d'acords)
    acords: list[AcordTab]
    seccio: int | None  # índex a Tab.seccions
    repeticio: int = 0  # 0 = original; 1, 2… = còpia per una marca "x2"/"bis" o una secció repetida
    heretada: bool = False  # acords copiats d'una altra estrofa (la tab no els escrivia aquí)
    origen: int = 0  # índex de la línia dins el content original (per a la columna i les còpies)


@dataclass
class SeccioTab:
    nom: str  # el de la pàgina, normalitzat ("Tornada", "Estrofa 2")
    tipus: str | None  # de structure.SECTION_TYPES, o None si no s'ha reconegut


@dataclass
class Tab:
    """Tab normalitzada i desplegada (repeticions expandides), al to de la pàgina (formes + capo)."""
    crua: TabCrua
    linies: list[LiniaTab]
    seccions: list[SeccioTab]
    transport: int = 0  # semitons per passar de les formes escrites al so (capo + correcció de to)
