# Pla — Transcriptor: de l'àudio a lletra + acords sincronitzats

> Viu a `.claude/PLAN_TRANSCRIPCIO.md` (repo del canconer) i se'n posa una còpia a l'arrel del repo nou `transcriptor`.
> Última revisió: 2026-10-15 (decisions i implementació de la Fase 6).

## Context

Avui les cançons entren al Cançoner via importadors que fan scraping de webs d'acords (acordscatala, cifraclub, Ultimate Guitar, guitartuna), amb qualitat irregular. Volem una eina que, donada una cançó (URL de YouTube o fitxer d'àudio), n'extregui **lletra, acords, tonalitat, tempo, compassos i seccions**, ho sincronitzi i generi el `content` amb `<ch>`/`<sec>` llest per a l'editor. Les dades de temps (en quin compàs/temps cau cada acord i cada paraula) es conserven per a funcions futures (acompanyaments).

**Decisions preses:**
- **Ruta**: pipeline d'eines open-source existents (sense entrenar cap model). Fine-tuning només com a fase opcional final si el benchmark ho justifica.
- **Lletra híbrida**: si hi ha text (enganxat, LRCLIB, o la BD si la cançó ja hi és) → alineació forçada; si no → transcripció amb Whisper.
- **Repo separat** (`C:\Users\Coco\VSC\transcriptor`), Python. S'integra al canconer al final.
- **Cua obligatòria**: ha de poder processar centenars de cançons desateses.
- **Pull-worker**: el worker demana feines a l'API del canconer amb connexions de sortida. Així funciona igual al PC, al servidor, a l'ordinador d'un amic o a una GPU al núvol, i el servidor continua sense acceptar connexions entrants. De moment **només en PCs** (no al servidor).
- **Funciona a Windows sense Docker**: a la llarga el worker serà una **aplicació de Windows instal·lable** (icona a la barra de tasques, activar/desactivar) perquè amics amb GPU hi puguin col·laborar. Per tant, **totes les dependències han de funcionar directament a Windows i a Linux**. Docker queda només per al servidor.
- **Sense `allin1`**: depèn de `natten` (extensió C++/CUDA sense versió per a Windows, i fixada a una versió antiga) i de `madmom` (difícil d'instal·lar en Python recent). Ritme amb **Beat This!** (només PyTorch) i estructura amb una **detecció pròpia per repeticions**. Tampoc s'usa **Essentia**, que no té versió per a Windows: la tonalitat surt dels acords.
- **CPU i GPU**: el codi detecta el dispositiu (`--device auto|cpu|cuda`) i tria precisió i models segons el que hi hagi.

**Estat (2026-10-15)**: Fases 0-7 fetes (Fase 7 sense provar l'instal·lador en un Windows net). La
Fase 6 és a la branca `transcripcio` del canconer, provada d'extrem a extrem contra `next dev` amb una
còpia de la BD, però encara sense fusionar ni desplegar. Protocol a `docs/api_worker.md`. Benchmark de
108 cançons: acords majmin 90 %, estructura 74 %, col·locació 46 %, to 98/108 (vegeu
`docs/benchmark.md`).

**Decisions de la Fase 6** (2026-10-15):
- **L'anàlisi és immutable**: és la sortida de la màquina (què passa a l'àudio) i no s'edita mai. Es
  guarda a `song_analyses`, **una fila per cançó** (reprocessar la sobreescriu), en una taula a part de
  `songs` perquè no pesi a les consultes de cançons (pàgina pública, PDF…) i perquè té metadades i un
  cicle de vida propis.
- **Sincronització derivada, no desada**: la relació "aquest `<ch>`/aquesta línia del `content` cau a tal
  temps" es calcula al moment alineant les paraules del `content` amb les de l'anàlisi (com la
  transferència ASR → text conegut). Cada acord pren el temps de la paraula on és escrit, així que
  afegir, treure, moure o corregir acords no trenca res. Els acords de línies sense lletra s'alineen per
  ordre dins la seva franja de temps. La funció dona una qualitat; per sota d'un llindar, aquella versió
  del `content` no té funcions de reproducció. No hi ha cap taula de cache: s'afegirà només si cal per
  rendiment. No s'afegeixen temps dins el `content` (el format `<ch>`/`<sec>` no canvia).
- **Format compacte (v2)** per a l'API i la BD: tuples i temps en ms enters, pulsacions com a diferències
  + índexs d'inici de compàs. Sense gzip (text JSON consultable). Conserva tota la informació (temps al
  ms, confiances a 0,001): 34 KB → 12 KB de mitjana.
- **`songs.bpm` i `songs.time_signature`**: metadades visibles i editables. El transcriptor les omple en
  crear la proposta; en mode `analyze`, només si són buides.
- **Dos modes de feina**: `new` (crea proposta) i `analyze` (enganxa l'anàlisi a una cançó existent sense
  tocar-ne el `content` ni crear proposta). `analyze` és el que dona temps a les cançons ja revisades.
- Si el `youtubeUrl` d'una cançó canvia, l'anàlisi deixa de ser vigent (és d'un altre àudio).
- Reintents: 3 intents; errors temporals ajornats 1 h / 2 h / 4 h; errors permanents de YouTube (vídeo no
  disponible, privat…) no es reintenten. Versió mínima del worker: variable d'entorn
  `TRANSCRIBER_MIN_VERSION`. Només URL de YouTube (pujar àudio, més endavant).

**Decisions de la Fase 0** (2026-10-15, detall a `docs/proves.md`):
- Separació: `htdemucs` en CPU, Mel-RoFormer (audio-separator) en GPU. `htdemucs_ft` descartat (8× més lent, sense millora). La separació és imprescindible per a la lletra.
- Acords: **BTC** (vocabulari gran), calculats sobre la mescla en paral·lel a la separació. Cal incorporar-ne el codi al repo i modernitzar-lo. Chordino i ChordFormer descartats.
- ASR: faster-whisper **large-v3-turbo** (large-v3 no millora i és 1,7× més lent).
- Lletra amb text conegut: **sense stable-ts** (col·lapsa en cançons llargues). Sempre es fa l'ASR i se'n **transfereixen els temps al text conegut** (Needleman-Wunsch amb coincidència aproximada). WhisperX + `softcatala/wav2vec2-large-xlsr-catala` com a refinament opcional (fixa torch 2.8: decidir-ne la integració a la Fase 1).
- LRCLIB: només text i tall de línies, amb reintents per als 503. Els seus temps no són fiables.
- Ritme: el compàs s'ha de regularitzar en postprocés (Beat This! compta corxeres en 6/8 i té inicis de compàs erràtics amb síncopes).

**Maquinari conegut** (només CPU de moment):
- Servidor `ssh nas`: i5-7500 (4 nuclis / 4 fils), 11 GB de RAM (~6,5 lliures), Ubuntu 26.04, sense GPU.
- PC: i7-6700 (4 nuclis / 8 fils), 16 GB. La GTX 750 Ti (2 GB, Maxwell) no serveix per al PyTorch actual. Python **no** està instal·lat (s'instal·larà amb `uv`).

**Cost estimat per cançó de 4 min en CPU**:
- separació de la veu: 1-3 min
- ritme: <1 min
- acords: <30 s
- lletra: ~1-2 min si s'alinea, 4-10 min si es transcriu amb Whisper large-v3 int8

**Total ~5-15 min**, és a dir, ~100-250 cançons/dia per màquina. Acceptable per a lots nocturns. Amb una GPU moderna, <1-2 min per cançó.

### Cançons de referència
Han de ser a la BD amb acords revisats, seccions marcades i `youtubeUrl` apuntant a l'**àudio d'estudi exacte** d'on surten els acords (amb `capo` si cal):
1. **"L'estaca", de Lluís Llach**: veu i guitarra, pocs acords, ritme regular. El cas fàcil.
2. **"Bon dia", d'Els Pets**: pop-rock amb bateria i tempo estable. Separació de veu i compàs amb banda.
3. **"La gent que estimo", d'Oques Grasses**: producció moderna i densa, metalls, ritme sincopat, veu amb efectes i cors. El cas difícil.

Més endavant se n'hi afegirà una en 3/4 per provar la detecció del compàs.

---

## Arquitectura

```
                 ┌──────────── repo transcriptor (Python) ────────────┐
URL / fitxer ──▶ │ fetch → separate → rhythm → chords → lyrics →       │──▶ SongAnalysis (JSON)
                 │ structure → merge   (cada etapa cacheja a disc)     │      + content <ch>/<sec>
                 └─────────────────────────────────────────────────────┘
   CLI: `tx run <url>`, `tx bench`, `tx worker --api ...`   ·  més endavant: app de Windows
                                    ▲  pull (HTTP sortint)
canconer: taula transcription_jobs ─┘  → resultat → proposta (com els importadors) + song_analyses
```

### Contracte central: `SongAnalysis` (JSON versionat)
```jsonc
{
  "version": 1,
  "source": { "url": "...", "youtube_id": "...", "duration_s": 241.3 },
  "meta":   { "title": "...", "artist": "...", "language": "ca" },
  "key":    { "tonic": "A", "mode": "minor", "confidence": 0.82 },
  "tempo":  { "bpm": 96.0, "time_signature": [4, 4] },
  "beats":  [ { "t": 0.52, "bar": 1, "beat": 1 }, ... ],          // downbeats = beat 1
  "chords": [ { "start": 0.52, "end": 2.98, "label": "Am", "raw": "A:min", "bar": 1, "beat": 1, "conf": 0.9 } ],
  "words":  [ { "start": 12.1, "end": 12.4, "text": "En", "conf": 0.95 } ],
  "lines":  [ { "start": 12.1, "end": 15.8, "word_range": [0, 7], "section": 2 } ],
  "sections": [ { "start": 0.0, "end": 12.0, "label": "intro", "name": "Intro" } ],
  "lyrics_source": "lrclib" | "user" | "db" | "whisper",
  "models": { "separation": "htdemucs_ft", "chords": "btc-large", "device": "cpu", ... }
}
```
- `content` (format `<ch>`/`<sec>`) és una **vista derivada** del JSON, no la font de veritat.
- Sortida cap al canconer amb la mateixa forma que `ImportResult` (`src/lib/importers/types.ts` del canconer): `{ title, artist, key, capo, language, tags, content }`, i a més l'`analysis`.
- Aquest és el format de treball del Python. Cap al canconer viatja i s'hi desa el **format compacte v2** (`a_compacte()` / `de_compacte()` a `schema.py`, detall a `docs/api_worker.md`).

### Estructura del repo nou
```
transcriptor/
├── pyproject.toml            uv; Python 3.11; extres `cpu` i `cuda` (índexs de PyTorch corresponents)
├── PLAN_TRANSCRIPCIO.md      còpia d'aquest pla
├── docker/
│   ├── Dockerfile.cpu        per al servidor (Linux + ffmpeg + torch CPU)
│   ├── Dockerfile.cuda       base nvidia/cuda; mateix codi
│   └── compose.worker.yml
├── configs/                  perfils cpu.yaml / gpu.yaml + configs de benchmark
├── src/transcriptor/
│   ├── device.py             detecció de dispositiu i perfil: cuda (VRAM ≥ 6 GB → models grans, float16)
│   │                         o cpu (int8, models lleugers, threads = nuclis); override per config/CLI
│   ├── schema.py             SongAnalysis (pydantic) + versió
│   ├── cache.py              cache per etapa: work/<id>/<etapa>.{wav,json}
│   ├── stages/
│   │   ├── fetch.py          yt-dlp → wav; o fitxer local. ffmpeg via binari portable
│   │   ├── separate.py       Demucs htdemucs / htdemucs_ft (o Mel-RoFormer via audio-separator)
│   │   ├── rhythm.py         Beat This! → beats, downbeats, compàs, tempo
│   │   ├── chords.py         backend intercanviable: btc | chordino (si funciona a Windows) | chordformer
│   │   ├── key.py            to a partir dels acords (histograma ponderat + perfils de Krumhansl)
│   │   ├── lyrics_source.py  user > db > LRCLIB (API gratuïta, per títol+artista+durada)
│   │   ├── lyrics_align.py   temps per paraula: transferència ASR → text conegut (+ WhisperX/CTC opcional)
│   │   └── lyrics_asr.py     faster-whisper large-v3-turbo (int8 CPU / float16 GPU) sobre la veu separada
│   ├── structure.py          detecció pròpia de seccions (vegeu Fase 3)
│   ├── postprocess/
│   │   ├── chords_clean.py   quantitzar a pulsacions, eliminar acords < 1 pulsació, suavitzat,
│   │   │                     simplificació de vocabulari, notació del projecte
│   │   └── lines.py          tall de línies (LRC si n'hi ha; si no: pauses + inicis de compàs)
│   ├── merge.py              acords + paraules + línies + seccions → model intermedi
│   ├── render.py             SongAnalysis → content / ImportResult
│   ├── pipeline.py           orquestració + temps per etapa
│   ├── bench/                benchmark contra la BD (Fase 4)
│   ├── worker.py             client pull de la cua del canconer (Fase 6)
│   └── app/                  app d'escriptori de Windows (Fase 7)
└── tests/                    pytest: merge, render, chords_clean, structure (fixtures JSON, sense àudio)
```

---

## Fases

### Fase 0 — Preparació i proves de cada eina (1-2 sessions)
- Instal·lar `uv` al PC, crear el repo (`git init`, `.gitignore` amb `work/`, `out/`, models, àudio). Desenvolupament **directe a Windows**: és la prova de foc del requisit "funciona a Windows".
- Prova de cada eina amb les 3 cançons de referència. Per a cadascuna: (a) **s'instal·la a Windows amb `uv` sense compilar res?**, (b) temps en CPU, (c) qualitat a ull. Les candidates:
  - Separació: `demucs` (htdemucs vs htdemucs_ft) vs `audio-separator` (Mel-RoFormer).
  - Ritme: `beat_this` (Beat This!).
  - Acords: BTC (ISMIR19, vocabulari gran), Chordino (NNLS-Chroma via vamp, **comprovar a Windows**), ChordFormer (si hi ha pesos públics).
  - Lletra: `stable-ts` (alineació amb Whisper, agnòstica d'idioma) vs WhisperX (wav2vec2 català; **verificar** quin model català hi ha i si s'instal·la a Windows); `faster-whisper` large-v3 vs large-v3-turbo per a l'ASR.
  - Fonts de lletra: comprovar que LRCLIB té les 3 cançons.
- Sortida: taula de compatibilitat/temps/qualitat a `docs/proves.md` i elecció provisional de backends. Una eina que no s'instal·li a Windows sense compilar queda **descartada**.

### Fase 1 — Esquema i etapes (2-3 sessions)
- `schema.py` amb `SongAnalysis` v1. Cache per etapa (re-executar només el que canvia; imprescindible per iterar la fusió sense refer 10 min de càlcul).
- Etapes `fetch → separate → rhythm → chords → key → lyrics_*` com a funcions pures sobre fitxers, amb backend escollible per config.
- `device.py` des del principi: cada etapa rep el `device` i el perfil (cap `"cuda"` escrit a mà). Perfils `cpu` i `gpu` (p. ex. faster-whisper `int8` vs `float16`, Demucs `shifts` 0 vs 2, Whisper large-v3-turbo vs large-v3). Si CUDA falla (driver o VRAM), torna a CPU amb un avís, sense petar. Un sol model carregat alhora (alliberar entre etapes): el servidor va just de RAM.
- CLI `tx run <url|fitxer> [--lyrics fitxer.txt] [--title --artist] [--device]` → `out/<id>/analysis.json` + `content.txt`.

### Fase 2 — Postprocés d'acords i ritme (1-2 sessions)
- Assignar a cada acord `bar`/`beat` a partir de les pulsacions; quantitzar inicis a la pulsació més propera.
- Eliminar acords més curts d'una pulsació, fusionar repeticions, suavitzat.
- Mapatge de vocabulari a la notació del projecte: anglesa amb **sostinguts** (`Bb`→`A#`), sufixos compatibles amb `CHORD_MODIFIERS` de `src/lib/editor/chordFunctions.ts` del canconer (copiar-ne la llista com a constant). Nivell de simplificació configurable (`majmin` | `sevenths` | `full`).
- Tonalitat a partir de l'histograma d'acords ponderat per durada + perfils de Krumhansl. Format `key` del canconer (`A`, `Am`…).
- Opcional: suggeriment de cejilla (`src/lib/transpose.ts` del canconer com a referència).

### Fase 3 — Estructura, fusió i render a `<ch>`/`<sec>` (2-4 sessions, el nucli difícil)
- **Línies**: si la lletra ve de LRC (LRCLIB), les línies ja hi són. Si no: tallar per pausa > ~0,6 s, preferint inicis de compàs, amb longitud màxima de línia.
- **Col·locació d'acords**: per a cada acord, la paraula que el conté o la primera que comença just després (tolerància ~mitja pulsació). Si diversos acords cauen a la mateixa paraula, es reparteixen per posició de caràcter proporcional al temps. Acords en zones sense veu (intro, instrumental, solo) → línies només d'acords.
- **Estructura** (`structure.py`, substitueix `allin1`):
  1. Agrupar les línies en blocs, separats per silencis vocals llargs o zones instrumentals.
  2. Signatura de cada bloc: text normalitzat + seqüència d'acords relativa al compàs.
  3. Similitud entre blocs: lletra quasi igual i acords iguals → **Tornada**; lletra diferent i acords iguals → **Estrofa** (autonumerada); bloc únic amb acords nous cap al final → **Pont**.
  4. Abans de la primera veu: **Intro**. Després de l'última: **Outro**. Zones llargues sense veu enmig: **Instrumental** / **Solo**.
  5. Opcional, si cal reforçar-ho: matriu d'autosimilitud de chroma (només numpy/librosa) per confirmar fronteres.

  Noms segons `SECTION_TYPES` de `src/lib/editor/sections.ts` del canconer.
- `render.py` → `content` amb el format exacte de la BD (`<sec>X</sec>` en línia pròpia, `<ch>X</ch>` inline, línies separades per `\n`). Validar el round-trip amb `parse()`/`serialize()` de `src/lib/editor/model.ts` del canconer mitjançant un script `npx tsx`.
- Tests pytest amb fixtures JSON sintètics (sense àudio).

### Fase 4 — Benchmark contra la BD (2 sessions): decidir amb números
- Exportar (lectura, sobre una **còpia** de `data/canconer.db`) les cançons publicades amb `youtubeUrl`: `id, title, artist, key, capo, content, youtube_url` → `bench/dataset.jsonl`.
- Mètriques per cançó:
  - **Acords**: seqüència de la referència (acords del content, col·lapsant repeticions) contra la predita, amb alineament Needleman-Wunsch **invariant a transposició** (provar els 12 desplaçaments: el vídeo pot estar en un altre to o amb cejilla). Precisió a nivell `majmin` i `sevenths`.
  - **To**: encert exacte / relatiu / quinta.
  - **Lletra** (mode ASR): WER contra la lletra de la BD normalitzada.
  - **Col·locació**: amb la lletra de la BD alineada, quina part dels acords cau a la mateixa paraula que a la referència.
  - **Estructura**: coincidència de seccions (tipus i fronteres per línia) amb les `<sec>` de la referència.
- `tx bench --n 50 --config configs/x.yaml` → informe CSV/markdown. Comparar backends i ajustar llindars.
- Atenció: les referències de la BD també tenen errors. És una mesura de concordança, no la veritat absoluta.

### Fase 5 — Iteració de qualitat (obert)
- Ajustar paràmetres segons el benchmark. Casos difícils: cançons amb capo, sense bateria, en directe, producció densa.
- Opcional: postprocés amb LLM (Claude) quan la lletra ve d'ASR: corregir errors evidents de transcripció i proposar noms de secció, **sense tocar temps ni acords**.

### Fase 6 — Cua i integració al canconer ✅ (branca `transcripcio` del canconer)
Decisions a l'inici del document. Protocol complet a `docs/api_worker.md`.

**Al canconer** (convencions de `PROJECT_CONTEXT.md` §10-§13), migració `data/migrations/0001_transcripcio.sql` (només afegeix):
- `songs`: columnes noves `bpm` i `time_signature` (`"4/4"`), exposades a l'API de cançons i editables per `PUT`.
- `transcription_jobs`: `mode (new|analyze), source_url, title, artist, language, lyrics_text, song_id, status (queued|running|done|failed|cancelled), priority, worker_id, lease_until, attempts, not_before, error, result_song_id, elapsed_seconds, created_by, created_at, started_at, finished_at`.
- `transcription_workers`: `name, token_hash (SHA-256), active, device_info, app_version, last_seen_at, jobs_done, avg_seconds`. A part de NextAuth.
- `song_analyses`: `song_id (PK), job_id, youtube_id, duration_s, format_version, app_version, device, lyrics_source, analysis (JSON compacte v2), created_at`.
- Codi: `src/db/queries/transcriptions.ts` (cua, lease, resultat, admin), `src/lib/transcriber/` (token, usuari "Transcriptor", utilitats de ruta), `src/lib/schemas/transcriber.ts` (Zod, inclòs el format compacte).
- Endpoints:
  - Worker (token): `POST /api/transcriber/claim`, `/jobs/[id]/heartbeat`, `/result`, `/fail`. Fora del middleware d'analítiques.
  - Admin: `GET|POST /api/admin/transcriptions` (estat; encuar una o moltes, o `analyzeMissing` per a totes les públiques sense anàlisi), `PATCH /api/admin/transcriptions/[id]` (cancel·lar/reintentar), `POST /api/admin/transcription-workers` (crea i retorna el token un sol cop), `PATCH|DELETE /api/admin/transcription-workers/[id]`.
  - Lease de 10 min; les feines caducades tornen a la cua en el claim següent (sense temporitzador).
- UI: pestanya "Transcripcions" al panell d'admin (encuar per línies `url, títol, artista`, analitzar les publicades, cua amb estat/accions, workers i tokens). Al `NewSongStartPopup`, un enllaç de YouTube ofereix "Transcriure des de l'àudio".
- **Worker CLI** (`tx worker --api https://guitarreo.cat --token ... [--device auto]`): envia l'anàlisi compacta i classifica les fallades (`kind: permanent|temporary`).

**Pendent per tancar la fase**: fusionar la branca i desplegar; crear un worker a l'admin de producció i processar-hi 5 cançons reals des del PC.

### Fase 7 — App de Windows per a col·laboradors
- **Instal·lador petit** (MSI amb WiX, ~31 MB, amb `uv` i Python oficial signat: l’Inno Setup el bloqueja Smart App Control, vegeu installer/README.md). Al primer arrencament: detecta si hi ha GPU NVIDIA, instal·la PyTorch CPU o CUDA amb `uv` (0,5-2,5 GB) i descarrega els models (~3-5 GB) un sol cop. Una sola versió de l'instal·lable, sense necessitat de Python previ.
- **App a la barra de tasques** (PySide6 o UI web local): enganxar el token, interruptor activar/desactivar, "només quan l'ordinador estigui inactiu", límit de nuclis, arrencar amb Windows, estat (cançó actual, fetes, temps mitjà).
- **Actualitzacions**: autoactualització quan l'API demana una versió mínima més nova; `yt-dlp` s'actualitza sol (YouTube canvia sovint).
- Sense certificat de signatura de codi apareix l'avís de SmartScreen ("Executa igualment"). Acceptable per a amics; signar-lo costa ~100-300 €/any.
- Validació CUDA: com que no tenim GPU, una sessió puntual en una GPU llogada (RunPod/Vast, uns cèntims) amb les 3 cançons de referència.

### Fase 8 (opcional, futur): explotar l'anàlisi
- Visor sincronitzat (lletra/acords seguint el vídeo) i acompanyaments a partir de `beats` + `chords`.
- Primer pas: la funció de sincronització (TS, al canconer) `sync(anàlisi, content) → { temps de cada <ch>, inici/fi de cada línia, qualitat }`, calculada al moment (vegeu les decisions de la Fase 6). Validar-la amb les cançons del benchmark, que tenen anàlisi i `content` revisat.
- Fine-tuning del model d'acords amb el repertori propi si el benchmark mostra errors sistemàtics.

---

## Riscos coneguts
- **YouTube**: bloqueja IPs de centre de dades. Des d'IP residencial (servidor de casa, PC, amics) normalment va bé. Cal mantenir `yt-dlp` actualitzat i potser fer servir cookies. Alternativa sempre disponible: fitxer d'àudio.
- **Compatibilitat Windows**: qualsevol dependència amb extensions natives sense versió per a Windows queda descartada (motiu de treure `allin1` i Essentia).
- **Estructura sense `allin1`**: la detecció pròpia pot fallar en cançons sense repeticions clares. Es mesura a la Fase 4 i es reforça amb autosimilitud de chroma si cal.
- **RAM al servidor** (~6,5 GB lliures): Whisper large-v3 int8 (~3 GB) + Demucs hi caben justos. Les etapes s'executen en seqüència alliberant models, mai en paral·lel.
- **Qualitat d'acords** amb harmonia rica o producció densa: limitada (~60-70% amb sèptimes). Per això el resultat sempre entra com a proposta per revisar.
- **Lletra transcrita** sense referència: hi haurà errors segur. L'híbrid amb LRCLIB/BD ho mitiga.

## Verificació
- Fase 0: `docs/proves.md` amb les 3 cançons i totes les eines escollides instal·lades a Windows amb `uv sync`, sense compilar.
- Fases 1-3: `tx run` sobre les 3 cançons → enganxar el `content` en una cançó de prova a l'editor del canconer i revisar-lo visualment; round-trip amb `model.ts`; `pytest`.
- Fase 4: informe de benchmark amb ≥50 cançons. Objectiu orientatiu: ≥80% de concordança d'acords `majmin` en repertori de guitarra.
- Fase 6: encuar 5 cançons des de l'admin, executar el worker al PC i veure-les aparèixer com a propostes. Matar el worker a mig procés: la feina torna a la cua. Dos workers alhora no agafen mai la mateixa feina, i un token revocat és rebutjat. `npx tsc --noEmit` al canconer.
  Fet en local (2026-10-15): prova d'extrem a extrem del worker real contra `next dev` amb una còpia de la BD (pipeline substituït per anàlisis de la cache): tokens, prioritat, concurrència, lease caducat, modes `new`/`analyze`, errors permanents i temporals, duplicats; rutes d'admin per HTTP. Falta la prova amb àudio real a producció.
- Fase 7: instal·lar l'app en un Windows net (sense Python), activar i desactivar el worker, processar una cançó. Imatge/instal·lació CUDA en una GPU llogada: el resultat és equivalent al de CPU, en molt menys temps. Sense GPU, torna a CPU sense petar.
