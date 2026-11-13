"""Dades crues d'una cançó: la sortida dels models i de l'àudio, abans del postprocés.

Amb aquestes dades es pot refer tot el postprocés (ritme, acords, lletra, estructura, estil) sense
l'àudio, en segons. El worker les envia al canconer amb cada resultat (`raw`, vegeu
docs/api_worker.md) i les rep de tornada en una feina `update` (vegeu versions.py).

Format: un .npz comprimit (zip) amb
- `json`: UTF-8 de {v, versio, meta, durada, ritme, asr, idioma_asr, lletra, separador,
  compute_type, per_trama, escala_groove, planor, fonts (opcional: les tabs d'acords trobades)}
- `acords`: probabilitats de BTC per trama (trames × 170) en uint8 sobre l'arrel quadrada, amb les
  menors de TALL_ACORDS a zero. Amb les 76 cançons de la cache dona els mateixos acords finals en
  ≥ 99,5 % del temps (mitjana 99,99 %) i ocupa ~30 KB per 3 minuts.
- `groove` (opcional): envolupants d'atacs (3 × trames) en uint8, escalades pel màxim de cada banda.
  Sense (dades d'una cache local sense àudio), l'estil es manté el de l'anàlisi anterior.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass

import numpy as np

FORMAT = 1
TALL_ACORDS = 1e-3


@dataclass
class Crues:
    meta: dict  # fetch: url, youtube_id, title, artist (o fitxer)
    durada: float
    ritme: dict  # Beat This!: pulsacions, inicis_compas
    probs: np.ndarray  # BTC: trames × 170
    per_trama: float
    asr: dict  # Whisper: paraules, segments, idioma
    idioma_asr: str | None
    lletra: dict | None  # {text, font} de la lletra feta servir (None: es tornarà a buscar)
    groove: dict | None  # {env (3, trames), planor} o None
    separador: str
    compute_type: str
    versio: str  # versió del transcriptor que les ha produït
    fonts: dict | None = None  # tabs d'acords trobades: {params, tabs} (stages/chords_source.py)


def empaqueta(c: Crues) -> bytes:
    dades = {
        "v": FORMAT, "versio": c.versio, "meta": c.meta, "durada": c.durada, "ritme": c.ritme,
        "asr": c.asr, "idioma_asr": c.idioma_asr, "lletra": c.lletra, "separador": c.separador,
        "compute_type": c.compute_type, "per_trama": c.per_trama,
    }
    if c.fonts is not None:
        dades["fonts"] = c.fonts
    p = np.asarray(c.probs, dtype=np.float32)
    arrays = {"acords": np.round(np.sqrt(np.where(p < TALL_ACORDS, 0, p)) * 255).astype(np.uint8)}
    if c.groove is not None:
        env = np.asarray(c.groove["env"], dtype=np.float32)
        escala = env.max(axis=1) + 1e-9
        arrays["groove"] = np.round(env / escala[:, None] * 255).astype(np.uint8)
        dades["escala_groove"] = [float(x) for x in escala]
        dades["planor"] = float(c.groove["planor"])
    arrays["json"] = np.frombuffer(json.dumps(dades, ensure_ascii=False).encode("utf-8"), dtype=np.uint8)
    sortida = io.BytesIO()
    np.savez_compressed(sortida, **arrays)
    return sortida.getvalue()


def desempaqueta(contingut: bytes) -> Crues:
    with np.load(io.BytesIO(contingut), allow_pickle=False) as z:
        dades = json.loads(z["json"].tobytes().decode("utf-8"))
        if dades.get("v") != FORMAT:
            raise ValueError(f"Format de paquet desconegut: {dades.get('v')}")
        probs = (z["acords"].astype(np.float32) / 255) ** 2
        groove = None
        if "groove" in z.files:
            escala = np.asarray(dades["escala_groove"], dtype=np.float32)
            groove = {"env": z["groove"].astype(np.float32) / 255 * escala[:, None], "planor": dades["planor"]}
    return Crues(meta=dades["meta"], durada=dades["durada"], ritme=dades["ritme"], probs=probs,
                 per_trama=dades["per_trama"], asr=dades["asr"], idioma_asr=dades["idioma_asr"],
                 lletra=dades["lletra"], groove=groove, separador=dades["separador"],
                 compute_type=dades["compute_type"], versio=dades["versio"], fonts=dades.get("fonts"))
