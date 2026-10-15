# Transcriptor

Donada una cançó (URL de YouTube o fitxer d'àudio), n'extreu lletra, acords, tonalitat, tempo,
compassos i seccions, i genera el `content` amb `<ch>`/`<sec>` per a l'editor d'El Cançoner
(guitarreo.cat).

- Pla complet: [PLAN_TRANSCRIPCIO.md](PLAN_TRANSCRIPCIO.md)
- Proves d'eines (Fase 0): [docs/proves.md](docs/proves.md)
- Benchmark i qualitat (Fases 4-5): [docs/benchmark.md](docs/benchmark.md)
- Protocol del worker (proposta per a la Fase 6): [docs/api_worker.md](docs/api_worker.md)
- Instal·lador de Windows (Fase 7): [installer/README.md](installer/README.md)

Requisit: tot s'instal·la a Windows i Linux amb `uv`, sense Docker i sense compilar res.

## Instal·lació (desenvolupament)

```bash
uv sync --extra cpu            # o --extra cuda (PyTorch cu126)
uv sync --extra cpu --extra app --extra ctc   # + app d'escriptori i afinament CTC
uv run tx models               # baixa els models per endavant (~2 GB)
```

## Ús

```bash
# Una cançó (la lletra es busca a LRCLIB; si no hi és, es transcriu amb Whisper)
uv run tx run "https://www.youtube.com/watch?v=J-fFsUFAnUc" --title "L'estaca" --artist "Lluís Llach"
# Amb la lletra coneguda (té prioritat)
uv run tx run cançó.mp3 --lyrics lletra.txt --title ... --artist ...
# → out/<id>/content.txt, analysis.json (SongAnalysis), proposta.json (ImportResult)

# Benchmark contra la BD del canconer (dataset exportat a work/bench/)
uv run tx bench --nom prova [--ids 110,111] [--nomes-postproces]

# Worker (quan existeixi l'API de la Fase 6)
uv run tx worker --api https://guitarreo.cat --token ...

# App d'escriptori
uv run pythonw -m transcriptor.app
```

`--device auto|cpu|cuda`: per defecte detecta la GPU i, si CUDA falla, torna a CPU.

Validar un `content` amb el codi real del canconer (round-trip `parse`/`serialize`, seccions, acords):

```bash
node --experimental-strip-types tools/valida_content.mts out/<id>/content.txt
```

## Pipeline

```
fetch (yt-dlp + ffmpeg portable) → separate (htdemucs | Mel-RoFormer) → rhythm (Beat This!)
→ chords (BTC, probabilitats per trama) → lyrics_source (usuari > BD > LRCLIB) → ASR (Whisper turbo)
→ postprocés: compàs (Viterbi, inclou 6/8) · acords per pulsació (Viterbi) · to (Krumhansl) · cejilla
→ temps per paraula (transferència ASR → text) → merge → estructura (repeticions) → render
```

Cada etapa cara es desa a `work/cache/<id>/`: canviar el postprocés i tornar a executar tarda segons.

## Tests

```bash
uv run pytest
```
