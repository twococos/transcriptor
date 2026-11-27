"""D'on surten les cançons del depurador i com se'n refà el postprocés.

Cada cançó té una clau:
- `banc-<id>`: work/bench/dataset.jsonl, amb l'àudio a work/bench/audio i la cache a work/cache.
  La referència és el content de la BD (còpia del banc).
- `local-w-<cache>` / `local-a-<cache>`: una cache local (w: work/cache; a: la de l'app, a
  %LOCALAPPDATA%/Transcriptor/dades/cache), de `tx run` o del worker de l'app. Sense referència; si
  hi ha l'anàlisi desada (fetes de l'app o out/ de `tx run`), es compara.
- `fitxer-<hash>`: un analysis.json qualsevol (`tx depura <fitxer>`) sense cache: només l'anàlisi.

El postprocés mai calcula etapes cares: només fa servir dades crues ja fetes. Les cançons del
canconer es veuen al depurador de la web, amb la traça que hi puja el worker amb cada resultat.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..cache import Cache
from ..config import Config, dir_base
from ..device import Perfil, detecta
from ..paquet import Crues, de_cache
from ..pipeline import Entrada, SenseDadesCrues, crues
from ..schema import SongAnalysis
from ..stages.fetch import id_canco, youtube_id

DATASET = Path("work/bench/dataset.jsonl")
AUDIO = Path("work/bench/audio")
ETAPES = ("rhythm.json", "chords.npz", "lyrics_asr.json", "fetch.json")


class ErrorOrigen(Exception):
    pass


@dataclass
class Origen:
    origen: str  # banc | local | fitxer
    id: str | int
    titol: str
    artista: str
    youtube_id: str | None = None
    entrada: Entrada | None = None
    dades: Crues | None = None  # None: només l'anàlisi (`previa`)
    cache: Cache | None = None
    previa: SongAnalysis | None = None
    referencia: dict | None = None  # per a bench.runner.avalua: id, title, artist, state, content, key, capo
    desada: dict | None = None  # anàlisi desada per comparar: {nom, analisi, content}
    audio: Path | None = None
    perfil: Perfil | None = None
    avisos: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)


def dir_traces() -> Path:
    return dir_base() / "depura"


def dir_dades_app() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    d = Path(base) / "Transcriptor" / "dades" if base else None
    return d if d and d.is_dir() else None


def dirs_cache() -> dict[str, Path]:
    """w: la cache de work/ (o TX_HOME); a: la de l'app d'escriptori, si n'hi ha i és una altra."""
    dirs = {"w": dir_base() / "cache"}
    app = dir_dades_app()
    if app and (app / "cache").is_dir() and (app / "cache").resolve() != dirs["w"].resolve():
        dirs["a"] = app / "cache"
    return dirs


def dataset() -> list[dict]:
    if not DATASET.exists():
        return []
    return [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]


def audio_de(id_c: int | str) -> Path | None:
    return next(AUDIO.glob(f"{id_c}.*"), None) if AUDIO.is_dir() else None


def normalitza_clau(clau: str) -> str:
    """"100" → banc-100, "local:w-yt-…" → local-w-yt-…."""
    clau = clau.strip().replace(":", "-", 1)
    return f"banc-{clau}" if clau.isdigit() else clau


def _completa(d: Path) -> bool:
    return all((d / f).exists() for f in ETAPES)


def _cache_local(yt: str | None) -> Path | None:
    if not yt:
        return None
    for d in dirs_cache().values():
        if _completa(d / f"yt-{yt}"):
            return d / f"yt-{yt}"
    return None


def _analisi_desada(yt: str | None, cache_id: str) -> dict | None:
    """L'anàlisi que ja es va fer d'aquesta cançó: la de l'app (fetes/) o la de `tx run` (out/)."""
    candidats = [Path("out") / (yt or cache_id)]
    app = dir_dades_app()
    if app and (app / "fetes").is_dir() and yt:
        for f in sorted((app / "fetes").glob("*/analysis.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("source", {}).get("youtube_id") == yt:
                    candidats.insert(0, f.parent)
                    break
            except (OSError, ValueError):
                continue
    for d in candidats:
        if (d / "analysis.json").exists():
            content = (d / "content.txt").read_text(encoding="utf-8") if (d / "content.txt").exists() else ""
            nom = "app" if "fetes" in d.parts else "tx run"
            return {"nom": f"Desada ({nom})", "analisi": json.loads((d / "analysis.json").read_text(encoding="utf-8")),
                    "content": content}
    return None


def prepara(clau: str, refes: bool = False) -> Origen:
    tipus, _, resta = normalitza_clau(clau).partition("-")
    try:
        if tipus == "banc":
            return _banc(int(resta))
        if tipus == "local":
            base, _, cache_id = resta.partition("-")
            return _local(base, cache_id)
        if tipus == "fitxer":
            return _fitxer(resta)
    except ValueError as e:
        raise ErrorOrigen(f"Clau invàlida: {clau} ({e})") from e
    raise ErrorOrigen(f"Clau desconeguda: {clau}")


def _banc(id_c: int) -> Origen:
    canco = next((c for c in dataset() if c["id"] == id_c), None)
    if canco is None:
        raise ErrorOrigen(f"La cançó {id_c} no és al banc ({DATASET})")
    audio = audio_de(id_c)
    if audio is None:
        raise ErrorOrigen(f"No trobo l'àudio de la cançó {id_c} a {AUDIO}")
    from ..audio import durada as durada_audio

    cfg = Config.carrega(None, lrclib=False)  # com tx bench
    perfil = detecta("auto")  # els paràmetres de la cache depenen del perfil (separador, Whisper)
    cache = Cache(id_canco(str(audio)))
    entrada = Entrada(font=str(audio), titol=canco["title"], artista=canco["artist"], content_bd=canco["content"])
    font_durada = cache.cami("audio.wav") if cache.cami("audio.wav").exists() else audio
    try:
        dades, _ = crues(entrada, cfg, perfil, cache, lambda i: None, None, sense_audio=True,
                         durada=durada_audio(font_durada))
    except SenseDadesCrues as e:
        raise ErrorOrigen(f"A la cache del banc hi falta l'etapa {e}: passa `tx bench --ids {id_c}`") from e
    return Origen(origen="banc", id=id_c, titol=canco["title"], artista=canco["artist"],
                  youtube_id=youtube_id(canco.get("youtube_url") or ""), entrada=entrada, dades=dades, cache=cache,
                  referencia=canco, audio=audio, perfil=perfil, info={"estat": canco["state"]})


def _local(base: str, cache_id: str) -> Origen:
    dirs = dirs_cache()
    if base not in dirs or not cache_id or "/" in cache_id or "\\" in cache_id:
        raise ErrorOrigen(f"Cache desconeguda: {base}-{cache_id}")
    d = dirs[base] / cache_id
    if not _completa(d):
        raise ErrorOrigen(f"A {d} hi falten dades crues ({', '.join(f for f in ETAPES if not (d / f).exists())})")
    desada = _analisi_desada(cache_id[3:] if cache_id.startswith("yt-") else None, cache_id)
    durada = desada["analisi"]["source"]["duration_s"] if desada else None
    dades = de_cache(d, durada)
    meta = dades.meta
    # Títol, artista i tabs: els de la cerca de tabs, si n'hi ha (així es reaprofiten les tabs baixades)
    params = (dades.fonts or {}).get("params") or {}
    lletra = json.loads((d / "lyrics_source.params.json").read_text(encoding="utf-8")) \
        if (d / "lyrics_source.params.json").exists() else {}
    titol = params.get("titol") or lletra.get("titol") or meta.get("title") or cache_id
    artista = params.get("artista") or lletra.get("artista") or meta.get("artist") or ""
    entrada = Entrada(font=meta.get("url") or meta.get("fitxer") or cache_id, titol=titol, artista=artista,
                      urls_acords=list(params.get("urls") or []), urls_bloquejades=list(params.get("bloquejades") or []))
    avisos = []
    if dades.lletra is None:
        avisos.append("La cache no té la lletra feta servir: es farà servir la de Whisper")
        dades.lletra = {"text": None, "font": "whisper"}
    return Origen(origen="local", id=f"{base}-{cache_id}", titol=titol, artista=artista,
                  youtube_id=meta.get("youtube_id"), entrada=entrada, dades=dades,
                  cache=Cache(f"local-{base}-{cache_id}", base=dir_traces() / "cache"),
                  previa=SongAnalysis.model_validate(desada["analisi"]) if desada else None, desada=desada,
                  audio=d / "audio.wav" if (d / "audio.wav").exists() else None, avisos=avisos,
                  info={"cache": str(d)})


def _registre() -> Path:
    return dir_traces() / "fitxers.json"


def registra_fitxer(cami: str | Path) -> str:
    """La clau per obrir un analysis.json (o el directori que el conté): la de la seva cache local si
    n'hi ha, o `fitxer-<hash>` (es recorda el camí a work/depura/fitxers.json)."""
    f = Path(cami)
    if f.is_dir():
        f = f / "analysis.json"
    if not f.is_file():
        raise ErrorOrigen(f"No trobo {f}")
    a = json.loads(f.read_text(encoding="utf-8"))
    yt = (a.get("source") or {}).get("youtube_id")
    if (local := _cache_local(yt)) is not None:
        base = next(k for k, v in dirs_cache().items() if local.parent == v)
        return f"local-{base}-{local.name}"
    h = hashlib.sha1(str(f.resolve()).encode()).hexdigest()[:10]
    reg = json.loads(_registre().read_text(encoding="utf-8")) if _registre().exists() else {}
    reg[h] = str(f.resolve())
    _registre().parent.mkdir(parents=True, exist_ok=True)
    _registre().write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"fitxer-{h}"


def _fitxer(h: str) -> Origen:
    reg = json.loads(_registre().read_text(encoding="utf-8")) if _registre().exists() else {}
    if h not in reg or not Path(reg[h]).is_file():
        raise ErrorOrigen(f"No sé quin fitxer és fitxer-{h}: obre'l amb `tx depura <camí>`")
    f = Path(reg[h])
    a = SongAnalysis.model_validate_json(f.read_text(encoding="utf-8"))
    content = (f.parent / "content.txt").read_text(encoding="utf-8") if (f.parent / "content.txt").exists() else ""
    audio = Path(a.source.fitxer) if a.source.fitxer and Path(a.source.fitxer).is_file() else None
    return Origen(origen="fitxer", id=h, titol=a.meta.title or f.parent.name, artista=a.meta.artist or "",
                  youtube_id=a.source.youtube_id, previa=a,
                  desada={"nom": "Fitxer", "analisi": a.model_dump(mode="json"), "content": content}, audio=audio,
                  avisos=["Sense dades crues (cap cache local d'aquesta cançó): només es mostra l'anàlisi"],
                  info={"fitxer": str(f)})


def locals_() -> list[dict]:
    """Les caches locals amb dades crues completes (sense les del banc, que ja surten al banc)."""
    sortida = []
    for base, arrel in dirs_cache().items():
        if not arrel.is_dir():
            continue
        for d in arrel.iterdir():
            if not d.is_dir() or not _completa(d):
                continue
            try:
                meta = json.loads((d / "fetch.json").read_text(encoding="utf-8"))
                lletra = json.loads((d / "lyrics_source.params.json").read_text(encoding="utf-8")) \
                    if (d / "lyrics_source.params.json").exists() else {}
            except (OSError, ValueError):
                continue
            if "bench" in (meta.get("fitxer") or "").replace("\\", "/").split("/"):
                continue
            sortida.append({"clau": f"local-{base}-{d.name}", "lloc": "app" if base == "a" else "work",
                            "titol": lletra.get("titol") or meta.get("title") or d.name,
                            "artista": lletra.get("artista") or meta.get("artist") or "",
                            "youtube_id": meta.get("youtube_id"), "audio": (d / "audio.wav").exists(),
                            "data": (d / "rhythm.json").stat().st_mtime})
    return sorted(sortida, key=lambda x: -x["data"])


def audio_de_clau(clau: str) -> Path | None:
    """L'àudio local d'una cançó, si n'hi ha (si no, el visor fa servir YouTube)."""
    tipus, _, resta = normalitza_clau(clau).partition("-")
    if tipus == "banc" and resta.isdigit():
        return audio_de(int(resta))
    if tipus == "local":
        base, _, cache_id = resta.partition("-")
        d = dirs_cache().get(base)
        f = d / cache_id / "audio.wav" if d and "/" not in cache_id and "\\" not in cache_id else None
        return f if f and f.exists() else None
    if tipus == "fitxer":
        try:
            return _fitxer(resta).audio
        except ErrorOrigen:
            return None
    return None
