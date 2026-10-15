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

A Windows amb **Smart App Control** actiu, el Python que baixa uv (python-build-standalone) queda
bloquejat perquè no està signat. Cal el Python oficial de python.org (signat), i que l'entorn el faci servir:

```powershell
winget install --id Python.Python.3.11 -e --scope user
uv sync --extra cpu --extra app --python "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
```

```bash
uv sync --extra cpu            # o --extra cuda (PyTorch cu126)
uv sync --extra cpu --extra app --extra ctc   # + app d'escriptori i afinament CTC
uv run --no-sync tx models     # baixa els models per endavant (~2 GB)
```

**Sempre `uv run --no-sync`** (o activar `.venv`): un `uv run` sense els `--extra` torna a
sincronitzar l'entorn i en treu PyTorch CPU, l'app i el CTC.

## Ús

```bash
# Una cançó (la lletra es busca a LRCLIB; si no hi és, es transcriu amb Whisper)
uv run --no-sync tx run "https://www.youtube.com/watch?v=J-fFsUFAnUc" --title "L'estaca" --artist "Lluís Llach"
# Amb la lletra coneguda (té prioritat)
uv run --no-sync tx run cançó.mp3 --lyrics lletra.txt --title ... --artist ...
# → out/<id>/content.txt, analysis.json (SongAnalysis), proposta.json (ImportResult)

# Benchmark contra la BD del canconer (dataset exportat a work/bench/)
uv run --no-sync tx bench --nom prova [--ids 110,111] [--nomes-postproces]

# Worker (quan existeixi l'API de la Fase 6)
uv run --no-sync tx worker --api https://guitarreo.cat --token ...

# App d'escriptori
uv run --no-sync pythonw -m transcriptor.app
```

Revisar a ull la sincronització d'una anàlisi (pulsació, compàs, acord i paraula en directe, línia de
temps, clic de metrònom, acords sonors i notes d'errors copiables):

```bash
uv run --no-sync tx visor work/bench/resultats/final/1      # àudio local (source.fitxer)
uv run --no-sync tx visor out/J-fFsUFAnUc                   # sense àudio al disc: vídeo de YouTube
uv run --no-sync tx visor out/<id> --audio cançó.mp3        # àudio explícit (més precís que YouTube)
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
→ postprocés: compàs (Viterbi, inclou 6/8) · acords per pulsació (Viterbi) · to (funcional) · cejilla
→ temps per paraula (transferència ASR → text) → merge → estructura (repeticions) → render
```

Cada etapa cara es desa a `work/cache/<id>/`: canviar el postprocés i tornar a executar tarda segons.

## Tests

```bash
uv run --no-sync pytest
```

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

L'instal·lador de Windows (`Transcriptor-<versió>.msi`) es construeix a GitHub Actions a partir
d'aquest repositori ([instal-lador.yml](.github/workflows/instal-lador.yml)) i el signa SignPath.

- Autors, revisors i aprovadors: [@twococos](https://github.com/twococos).
- Cada publicació signada l'aprova manualment un aprovador.

### Privacitat

El Transcriptor no envia cap informació a cap sistema de la xarxa si l'usuari no ho demana:

- Baixa l'àudio de l'URL que se li indica (YouTube, amb yt-dlp), la lletra de [LRCLIB](https://lrclib.net)
  i, el primer cop, els models (Hugging Face, GitHub).
- El worker i l'app d'escriptori només es connecten al servidor d'El Cançoner que l'usuari configura
  (per defecte `https://guitarreo.cat`) i amb el token que l'usuari hi introdueix. Hi envien el
  resultat de les feines, la versió del Transcriptor, el nom de l'ordinador i el dispositiu de
  càlcul (CPU o el model i la memòria de la GPU). Sense token
  configurat, no s'hi connecten.
- L'app desa en aquest ordinador les cançons que ha fet (anàlisi i, opcionalment, l'àudio) per
  obrir-les al visor. No s'envien enlloc i es poden esborrar des de l'app.
