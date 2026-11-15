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
from pathlib import Path

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


def _llegeix(d: Path, nom: str) -> dict | list:
    return json.loads((d / nom).read_text(encoding="utf-8"))


def de_cache(d: Path, durada: float | None = None, versio: str = "") -> Crues:
    """Les dades crues tal com són al directori d'una cache local (cache.py), sense comprovar-ne els
    paràmetres: per refer el postprocés d'una cançó ja feta (tools/revisa_*.py, depura/).

    Cal que hi siguin `rhythm.json`, `chords.npz`, `lyrics_asr.json` i `fetch.json`. Sense `durada`,
    la de `audio.wav` si encara hi és o, si no, l'última pulsació o paraula més un segon."""
    ritme = _llegeix(d, "rhythm.json")
    asr = _llegeix(d, "lyrics_asr.json")
    params_asr = _llegeix(d, "lyrics_asr.params.json") if (d / "lyrics_asr.params.json").exists() else {}
    acords = np.load(d / "chords.npz")
    groove = None
    if (d / "groove_env.npz").exists():
        g = np.load(d / "groove_env.npz")
        groove = {"env": g["env"], "planor": float(g["planor"])}
    lletra = _llegeix(d, "lyrics_source.json") if (d / "lyrics_source.json").exists() else None
    fonts = None
    if (d / "chords_source.json").exists() and (d / "chords_source.params.json").exists():
        fonts = {"params": _llegeix(d, "chords_source.params.json"), "tabs": _llegeix(d, "chords_source.json")}
    if durada is None and (d / "audio.wav").exists():
        import soundfile

        durada = float(soundfile.info(str(d / "audio.wav")).duration)
    if durada is None:
        durada = max([ritme["pulsacions"][-1] if ritme["pulsacions"] else 0.0]
                     + [w["end"] for w in asr["paraules"]]) + 1.0
    return Crues(meta=_llegeix(d, "fetch.json"), durada=durada, ritme=ritme, probs=acords["probs"],
                 per_trama=float(acords["per_trama"]), asr=asr, idioma_asr=params_asr.get("idioma"),
                 lletra=lletra, groove=groove, separador=params_asr.get("veu", "htdemucs"),
                 compute_type=params_asr.get("compute_type", "int8"), versio=versio, fonts=fonts)

