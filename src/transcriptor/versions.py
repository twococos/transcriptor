"""Quines versions del transcriptor han canviat el resultat de les anàlisis, i què cal refer.

Cada anàlisi del canconer recorda amb quina versió es va fer (o actualitzar per últim cop). Quan un
worker té una versió que canvia el resultat respecte d'aquella, el canconer la marca com a
desactualitzada i un worker la refà (feina `update`):
- El postprocés (fases 7–9 del pipeline: ritme, acords, lletra, estructura, estil) es refà sempre
  sencer a partir de les dades crues: és qüestió de segons.
- Les dades crues (sortida dels models i envolupants de l'àudio) només es refan si alguna versió
  posterior les ha canviat, i això necessita l'àudio.

En publicar una versió que canviï el resultat, afegiu-la a CANVIS amb el que canvia. Una versió que
només toca l'app o el worker no hi va: les anàlisis no han quedat enrere.
"""

from __future__ import annotations

POSTPROCES = "postproces"
# Dades crues: fetch (àudio), separate (veu), rhythm (Beat This!), chords (BTC), lyrics_asr (Whisper),
# groove (envolupants de l'acompanyament)
CRUES = {"fetch", "separate", "rhythm", "chords", "lyrics_asr", "groove"}

CANVIS: dict[str, set[str]] = {
    "0.1.8": {"groove"},  # estil rítmic de l'acompanyament (abans no hi era)
    "0.1.9": {POSTPROCES},  # correcció de la graella de pulsacions i BPM per mitjana
    "0.1.10": {POSTPROCES},  # temps de la primera paraula de frase de Whisper (postprocess/temps_asr.py)
    "0.1.11": {POSTPROCES},  # compassos als instrumentals; sense repetir l'acord a l'inici de línia
    "0.1.13": {POSTPROCES},  # acords per patrons de compàs; seccions contigües, a terra i amb l'acord després del títol
    "0.1.14": {POSTPROCES},  # acords i seccions contrastats amb tabs d'internet (fonts/)
}


def clau(versio: str | None) -> tuple[int, ...]:
    """"0.1.10" → (0, 1, 10). Una versió desconeguda o absent és la més antiga."""
    try:
        return tuple(int(x) for x in (versio or "").split("."))
    except ValueError:
        return ()


VERSIO_ANALISI = max(CANVIS, key=clau)  # l'última versió que ha canviat el resultat


def desactualitzada(versio: str | None) -> bool:
    return clau(versio) < clau(VERSIO_ANALISI)


def crues_a_refer(versio: str | None) -> set[str]:
    """Etapes crues que han canviat des de `versio` (buit: n'hi ha prou amb refer el postprocés)."""
    canviades: set[str] = set()
    for v, etapes in CANVIS.items():
        if clau(v) > clau(versio):
            canviades |= etapes & CRUES
    return canviades
