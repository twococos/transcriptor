# Protocol worker ↔ canconer

> Estat: **implementat** (Fase 6; estadístiques, `/me` i classificacions a la 0.1.7). Client: `src/transcriptor/worker.py`. Servidor (canconer):
> `src/app/api/transcriber/*` i `src/db/queries/transcriptions.ts`. Proves: `tests/test_worker.py`
> (servidor simulat) i una prova d'extrem a extrem contra `next dev` amb una còpia de la BD.

Tot són peticions **sortints** del worker (HTTPS, JSON). Autenticació amb un token per worker:
`Authorization: Bearer tx_…`. El canconer només en desa el SHA-256 (taula `transcription_workers`).
Els tokens es creen i es revoquen des de l'admin (pestanya "Transcripcions"); el token només es mostra
en crear-lo. L'API dels workers és fora del middleware d'analítiques.

## Respostes comunes

| Codi | Significat | Què fa el worker |
|---|---|---|
| 401 | Token desconegut o revocat | S'atura i ho mostra (codi de sortida 2) |
| 426 | Versió massa antiga. Cos: `{"min_version": "0.3.0"}` | S'atura i demana actualitzar (codi 3; l'app s'autoactualitza) |
| 409 | La feina ja no és d'aquest worker (lease caducat, cancel·lada…) | Abandona la feina |
| 5xx / xarxa | Error temporal | Reintenta amb espera creixent (30 s → 5 min) |

La versió mínima es configura al canconer amb la variable d'entorn `TRANSCRIBER_MIN_VERSION`.

## `POST /api/transcriber/claim`

Demana la següent feina: la de més `priority` i, a igualtat, la més antiga, saltant les que tenen
`not_before` en el futur. L'assignació és atòmica (transacció de better-sqlite3). Abans, les feines amb el
lease caducat tornen a la cua comptant un intent (no cal cap temporitzador al servidor).

Petició:
```json
{ "worker": "PC-Coco", "app_version": "0.1.0",
  "device": { "type": "cpu", "name": "Intel i7-6700", "vram_gb": 0 } }
```
Resposta `204`: no hi ha feina. Resposta `200`:
```json
{ "job": {
    "id": 42,
    "mode": "new",
    "source_url": "https://www.youtube.com/watch?v=XgwnYXOfIkk",
    "title": "Bon dia", "artist": "Els Pets",
    "language": "ca",
    "lyrics_text": null,
    "song_content": null,
    "lease_seconds": 600 } }
```
- `mode`:
  - `new`: el resultat crea una cançó pendent i una proposta a nom de l'usuari sistema "Transcriptor".
  - `analyze`: per a una cançó existent. `song_content` porta el seu `content` (el worker en fa servir la
    lletra, font "db") i el resultat **només** desa l'anàlisi; el `content` no es toca.
- `lyrics_text`: lletra enganxada per l'admin en encuar (opcional, té prioritat).
- `language`: opcional; si és null, l'idioma el detecta Whisper. **L'idioma de la BD no sempre és
  correcte** (p. ex. "La gent que estimo" hi consta com a `es`).

## `POST /api/transcriber/jobs/{id}/heartbeat`

Cos buit. Cada `lease_seconds / 3`. Allarga el lease. `409` = la feina ja no és d'aquest worker.

## `POST /api/transcriber/jobs/{id}/result`

```json
{ "proposal": { "title": "…", "artist": "…", "key": "A", "capo": 1, "language": "ca",
                "tags": "", "content": "<sec>…", "youtubeUrl": "…" },
  "analysis": { "v": 2, … },
  "stats": { "v": 1, … } }
```
- `stats` (opcional, des de la 0.1.7): com s'ha fet la feina. Vegeu [Estadístiques](#estadístiques-de-la-feina-stats-v1).
- `proposal` té la forma d'`ImportResult` (`src/lib/importers/types.ts` del canconer). En mode `analyze`
  s'ignora.
- `analysis` és l'anàlisi en **format compacte v2** (vegeu més avall). El canconer la valida amb Zod
  (`src/lib/schemas/transcriber.ts`) i la desa a `song_analyses` (una fila per cançó; reprocessar la
  sobreescriu). També omple `songs.bpm` i `songs.time_signature` (en mode `analyze`, només si són buits).
- Si en mode `new` ja existeix una cançó amb el mateix artista i títol, la feina queda fallada amb
  "Ja existeix (cançó N)".
- Respostes: `{"status": "ok", "songId": …, "proposalId": …}` o `{"status": "duplicate", "songId": …}`.

## `POST /api/transcriber/jobs/{id}/fail`

```json
{ "error": "RuntimeError: …", "released": false, "kind": "temporary" }
```
- `released: true`: el worker s'ha aturat a mitja feina (desactivat o Ctrl+C). Torna a la cua **sense**
  comptar com a intent.
- `kind: "permanent"`: no es reintentarà mai (vídeo no disponible, privat, amb restricció d'edat…; el
  worker ho deriva dels missatges de yt-dlp, `ErrorDescarrega`).
- `kind: "temporary"`: es reintenta més tard (`not_before` = ara + 1 h, 2 h, 4 h…) fins a 3 intents.

## `GET /api/transcriber/me`

Dades del worker del token: `{"id": 5, "name": "PC de la Marta", "active": true, "jobs_done": 12}`. El
nom el posa l'admin en crear el token; l'app el mostra (no es configura al worker) i, de pas, la crida
serveix per validar el token quan es desa. La versió mínima es comprova amb el `User-Agent`
(`transcriptor-worker/x.y.z`).

## `GET /api/transcriber/leaderboard`

Classificacions dels workers, de sempre i del mes en curs (UTC), amb la posició del que consulta:
```jsonc
{ "me": { "id": 5, "name": "Jo" },
  "min_songs_speed": 5,
  "periods": {
    "all":   { "songs": Board, "total_time": Board, "speed": Board },
    "month": { … } } }
// Board = { "top": [{ "rank": 1, "worker_id": 2, "name": "Marta", "value": 8, "me": false }, …3],
//           "me": { "rank": 4, "value": 3, "songs": 3 } | null }
```
- Compten les feines `done` (les duplicades i fallades no). Hi surten tots els workers, també els
  desactivats; un worker **eliminat** perd les seves feines (per revocar-lo, millor desactivar-lo).
- `songs`: nombre de cançons. `total_time`: segons (`elapsed_seconds`, mesurat pel servidor des del
  claim fins al resultat). `speed`: segons de càlcul per minut d'àudio (`Σ temps / Σ minuts`; com més
  baix, millor), amb un mínim de `min_songs_speed` cançons.
- Les feines amb alguna etapa de la cache local (`stats.timing.cached` no buit) compten com a cançó però
  no per als temps. Les feines sense `stats` (workers antics) no compten per a la rapidesa.
- `me.rank` és null si no hi arriba (rapidesa amb menys cançons del mínim; `me.songs` diu quantes en té).
- Empats: guanya qui hi va arribar primer.

## Estadístiques de la feina (`stats`, v1)

JSON obert, separat de l'anàlisi: l'anàlisi és *què hi ha a l'àudio*; les estadístiques, *com s'ha fet
aquesta feina*. Es desen a `transcription_jobs.stats` i l'app les desa també en local amb cada cançó.
El servidor només valida `v`, `audio.duration_s`, `timing.total_s` i `timing.cached` (els fa servir
per a les classificacions) i deixa passar la resta, fins a 32 KB. **Per afegir un camp nou n'hi ha
prou de posar-lo al worker** (`estadistiques.py`): l'admin i l'app el mostren amb el seu camí.

```jsonc
{ "v": 1, "app_version": "0.1.7",
  "device": { "type": "cpu", "name": "Intel i7-6700", "vram_gb": 0, "threads": 4 },
  "audio": { "duration_s": 214.0 },
  "timing": { "total_s": 470.7, "wall_s": 482.0,
              "stages_s": { "fetch": 6.2, "separate": 188.0, "rhythm": 21.3, "chords": 14.9,
                            "lyrics_source": 1.1, "lyrics_asr": 236.4, "postproces": 2.8 },
              "cached": [] },
  "lyrics": { "source": "lrclib", "align": "transfer-asr", "matched_ratio": 0.87, "timed_ratio": 0.93,
              "asr_mean_conf": 0.78, "discarded_lines": 2, "words": 214, "lines": 32 },
  "chords": { "count": 58, "distinct": 6, "mean_conf": 0.81, "vocabulary": "sevenths" },
  "key": { "label": "Am", "confidence": 0.74, "capo": 0 },
  "tempo": { "bpm": 96, "time_signature": "4/4" },
  "structure": { "sections": 8 },
  "models": { "separation": "htdemucs", "chords": "btc-large-voca", … },
  "warnings": [ "…" ],
  "checks": {} }   // reservat per a comprovacions futures (p. ex. acords contrastats amb una web)
```

| Camp | Què és |
|---|---|
| `timing.total_s` | Temps del pipeline. `wall_s`: des que el worker comença fins abans d'enviar. |
| `timing.stages_s` | Temps de cada etapa calculada (les de la cache no hi surten). |
| `timing.cached` | Etapes servides de la cache local (reprocessar una cançó ja feta). |
| `lyrics.matched_ratio` | Part del text conegut (BD, LRCLIB o enganxat) que l'alineació Needleman-Wunsch aproximada ha aparellat amb una paraula sentida per Whisper. No és un "% d'encert": diu quant del text s'ha pogut ancorar a l'àudio; per sota de 0,4 surt l'avís "potser no és la mateixa versió". Només amb lletra coneguda. |
| `lyrics.timed_ratio` | Part de les paraules finals amb temps propi (la resta s'interpolen). |
| `lyrics.asr_mean_conf` | Probabilitat mitjana que Whisper dona a cada paraula sentida. És la mesura de qualitat quan la lletra ve de Whisper. |
| `chords.mean_conf` | Probabilitat mitjana del camí de Viterbi dels acords (BTC), ponderada per durada. |
| `key.confidence` | Puntuació del to (perfils de Krumhansl). |

## Format compacte de l'anàlisi (v2)

Mateixa informació que `SongAnalysis` (`schema.py`), amb tuples i temps en mil·lisegons enters. Es
genera amb `a_compacte()` i es llegeix amb `de_compacte()`. Pèrdua: temps arrodonits al ms i
confiances a 0,001. Comprovat amb les 294 anàlisis de la cache: mitjana de 34 KB → 12 KB.

```jsonc
{
  "v": 2,
  "source": { "url": "…", "youtube_id": "…", "duration_s": 241.3 },
  "meta": { "title": "…", "artist": "…", "language": "ca" },
  "key": { "tonic": "A", "mode": "minor", "confidence": 0.82 },
  "capo": 0,
  "tempo": { "bpm": 96.0, "time_signature": [4, 4] },
  "beats": {
    "dt": [520, 618, 621, …],        // ms des de la pulsació anterior (la primera, des de 0)
    "downbeats": [2, 6, 10, …],      // índexs de les pulsacions amb beat 1
    "beat_exceptions": { "8": 4 }    // només si la numeració no és consecutiva (compassos irregulars)
  },
  "chords":   [[520, 2980, "Am", 0.9, 2], …],      // inici, fi, acord, conf, índex de pulsació | null (, raw si ≠ acord)
  "words":    [[12100, 12400, "En", 0.95], …],     // inici, fi, text, conf | null
  "lines":    [[12100, 15800, 0, 7, 2], …],        // inici, fi, paraula inicial, paraula final (exclosa), secció | null
  "sections": [[0, 12000, "intro", "Intro"], …],   // inici, fi, tipus, nom
  "lyrics_source": "lrclib",
  "models": { … }, "stage_times_s": { … }, "warnings": [ … ]
}
```
- El número de compàs no es desa: és el nombre de pulsacions amb beat 1 fins a cada pulsació (0 =
  anacrusi). El número de temps es compta des de l'últim inici de compàs; a l'anacrusi, enrere des del
  numerador del compàs.
- L'anàlisi és la sortida de la màquina i **no s'edita mai**. La sincronització amb el `content` (quin
  temps té cada `<ch>` i cada línia) es calcula al moment alineant les paraules del `content` amb
  `words` (Fase 8). Si el `youtubeUrl` de la cançó canvia, l'anàlisi deixa de ser vigent
  (`getCurrentSongAnalysis`).

## Decisions (Fase 6)

1. De moment els workers només corren en PCs (no al servidor).
2. 3 intents com a màxim; els errors temporals s'ajornen 1 h, 2 h, 4 h; els permanents no es reintenten.
   Un lease caducat compta com a intent (una cançó que fa petar el worker no el bloqueja per sempre).
3. Només URL de YouTube; pujar fitxers d'àudio queda per més endavant.
4. Versió mínima: variable d'entorn `TRANSCRIBER_MIN_VERSION`.
