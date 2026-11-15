# Depurador i visor (`tx depura`)

Eina local per veure què fa cada pas del postprocés i per trobar els problemes habituals de les
transcripcions. Obre qualsevol cançó feta pel transcriptor i se sincronitza amb YouTube o amb
l'àudio local, com `tx visor`.

```
uv run tx depura                          # obre http://localhost:8766/ amb la llista
uv run tx depura out/XgwnYXOfIkk          # un analysis.json (o el directori que el conté)
uv run tx depura web-123 --token tx_…     # una cançó del canconer (id de la cançó)
uv run tx depura 100                      # una cançó del banc
```

Executa-ho des del directori del transcriptor. El banc és a `work/bench/` i la cache a
`work/cache/` (o a `TX_HOME`).

## D'on surten les cançons

| Clau | Origen | Com es refà el postprocés | Referència |
|---|---|---|---|
| `banc-<id>` | `work/bench/dataset.jsonl` | Com `tx bench`, amb la cache de `work/cache` | content de la BD (còpia del banc) |
| `web-<id>` | una cançó del canconer amb anàlisi | Com un worker en una feina `update` | content de la cançó |
| `local-w-<cache>` | `work/cache/<cache>`, de `tx run` | Amb les dades crues de la cache | — |
| `local-a-<cache>` | la cache de l'app (`%LOCALAPPDATA%\Transcriptor\dades\cache`) | Amb les dades crues de la cache | — |
| `fitxer-<hash>` | un `analysis.json` sense cache local | No es refà: només es mostra l'anàlisi | — |

**`web-<id>`:**
- Es baixen a `work/depura/web/<id>.json` les mateixes dades que rebria un worker en una feina
  `update`:
  - dades crues;
  - content;
  - si l'ha escrit una persona;
  - tabs afegides o descartades a l'admin;
  - anàlisi vigent.
- Es refà el postprocés com ell (`worker.Worker._executa`).
- Si el canconer no té les dades crues (anàlisis d'abans de la 0.1.9), es busquen a les caches
  locals (`yt-<vídeo>`). Si tampoc hi són, només es mostra l'anàlisi.
- «Recalcula» les torna a baixar. Sense xarxa, es fan servir les de l'última vegada.

**`local-*`:**
- El títol, l'artista i les tabs afegides surten de la cerca de tabs de la cache, perquè es
  reaprofitin les tabs baixades.
- Si a l'app (`fetes/`) o a `out/` hi ha l'anàlisi que es va fer de la mateixa cançó, es compara.

Mai es calcula cap etapa cara (separació, Beat This, BTC, Whisper): només es fan servir dades crues
ja fetes. Amb les tabs sí: si els paràmetres de la cerca no coincideixen, es tornen a buscar a
internet, com faria el worker.

### API del canconer

Són dues rutes de només lectura, amb el token d'un worker (`Authorization: Bearer tx_…`), al
codi del canconer a `src/app/api/transcriber/songs/`:
- `GET /api/transcriber/songs?q=&limit=`: les cançons amb anàlisi, de la més recent a la més
  antiga, `{songs: [{id, title, artist, youtube_url, app_version, has_raw, analyzed_at}]}`.
- `GET /api/transcriber/songs/{id}`: el mateix que una feina `update` (`source_url`, `title`,
  `artist`, `language`, `song_content`, `song_content_human`, `chord_source_urls`,
  `chord_source_blocked`, `analysis`, `analysis_app_version`, `raw`), més `key`, `capo`, `state`,
  `transcriber_content`, `analyzed_at` i `raw_app_version`. 404 si la cançó no té anàlisi.

El token es pren, per ordre, de:
1. `tx depura --token` (i `--api`);
2. les variables `TX_TOKEN` / `TX_API`;
3. la configuració de l'app d'escriptori del mateix usuari de Windows.

## Com funciona

Quan s'obre una cançó, el servidor executa `python -m transcriptor.depura.genera <clau>` en un
subprocés i desa la traça a `work/depura/<clau>/traca-<codi>.json`, on `codi` és un hash del codi
font. Si el codi no ha canviat, la traça es reaprofita. Si has editat el postprocés, en obrir la
cançó es recalcula sola (~2–20 s), i no cal reiniciar el servidor. «Recalcula» la força.

La traça la graven `pipeline.executa(traca=...)`, `fonts/aplica.aplica` i
`postprocess/seccions.quadra` (vegeu `traca.py`). Sense traça no canvien res. Passos:

| Pas | Què hi ha |
|---|---|
| `ritme` | pulsacions de Beat This crues, correccions (octava/forat/extrem), BPM, compàs |
| `probabilitats` | top-6 de BTC per pulsació (vocabulari col·lapsat) |
| `acords_audio` | acords del Viterbi només amb l'àudio |
| `lletra` | paraules de Whisper (crues), correccions de `temps_asr`, paraules alineades, línies, descartades |
| `fonts` | cada tab: normalitzada, alineada (acord, pes, plausible), pes, grup, motiu de descart; bonificació del consens |
| `acords_fonts` | acords finals amb `origen` (àudio / confirmat / substituït) |
| `estructura` | elements de `merge.colloca` + seccions de `structure.detecta` + el content en aquest punt |
| `seccions_fonts` | seccions després de contrastar-les amb les tabs (amb `vot_cua`) + content |
| `quadra` | per secció: candidata, frontera triada, compassos, cost desglossat; seccions eliminades; cues escrites al final de la línia |
| `final` | elements, seccions i content finals |

`genera.py` també afegeix:
- el content sense tabs (segona passada amb `fonts_acords=False`);
- la referència col·locada al temps;
- l'anàlisi desada per comparar;
- les mètriques del banc respecte de la referència;
- les rodes i quasi-rodes de cada zona instrumental (`rodes.quasi_rodes`).

## Vistes

- **Llista**: tres pestanyes.
  - **Banc**: les mètriques d'un run i la diferència respecte d'un altre. «Problemes de tot el banc»
    compta els avisos de totes les cançons.
  - **Web**: cerca al canconer.
  - **Caches locals**: les de `work/cache` i les de l'app, sense les del banc.
- **Reproductor**:
  - El vídeo de YouTube, amb el mateix suavitzador i desplaçament que el visor, o l'àudio local
    (el del banc, o `audio.wav` de la cache si encara hi és).
  - Velocitat, clic de pulsació i acords sonors programats amb antelació.
  - En directe: compàs, acord actual i següent, secció i línia amb la paraula que sona.
- **Línia de temps**:
  - Carrils que es poden activar o amagar:
    - compassos i pulsacions crues;
    - BTC (top-3 per pulsació);
    - acords d'àudio;
    - una línia per tab;
    - consens;
    - acords finals;
    - referència;
    - acords i seccions de l'anàlisi comparada;
    - lletra alineada i Whisper;
    - seccions a cada pas;
    - notes.
  - Clic: detall de l'instant, notes i «Copia informe» (markdown per enganxar al xat).
  - Roda: zoom. Arrossegar: desplaça. Majúscules + arrossegar: bucle. Espai: reprodueix.
    Fletxes: compàs anterior / següent. C: clic. A: acords.
- **Content**: dos contents costat a costat, aparellats per lletra.
  - Es pot triar entre: referència, anàlisi comparada, sense tabs, estructura detectada, seccions de
    les tabs i final.
  - Els acords es comparen al so (major/menor) i a la mateixa paraula.
- **Fonts**: cada tab tal com s'ha llegit. Cada acord es pinta segons si l'àudio el permet, amb el
  pes, l'encaix i el motiu de descart.
- **Seccions**: la taula de costos de `quadra`, les cues absorbides i les rodes / quasi-rodes.
- **Lletra i ritme**: correccions de Whisper i de pulsacions, línies descartades, paraules dubtoses
  i la corba de tempo.
- **Problemes**: avisos automàtics amb enllaç al temps:
  - seccions que no són ×4;
  - instrumentals curts;
  - substitucions de les tabs amb l'àudio segur;
  - l'àudio contra totes les tabs;
  - tabs descartades o en un altre to;
  - quasi-rodes;
  - acords diferents de la referència…

## Referència al temps

Els acords de la referència es col·loquen amb el mateix aparellament que `metrics.collocacio`:
- Cada línia de lletra s'aparella per text, en ordre, amb una línia de l'anàlisi, i l'acord va a
  l'inici de la paraula on és escrit.
- Els acords de les línies sense lletra es reparteixen entre les línies aparellades del costat i
  surten ratllats (posició aproximada).
- Es transposen al so amb el transport detectat i el capo de l'anàlisi.

Un acord de la referència coincideix si l'acord final té la mateixa classe major/menor a menys
d'un temps.

## Fitxers

- `work/depura/<clau>/traca-<codi>.json`: traces.
- `work/depura/web/<id>.json`: dades baixades del canconer.
- `work/depura/cache/<clau>/`: cache de proves, perquè no es toqui la de l'app ni la del banc.
- `work/depura/fitxers.json`: els `analysis.json` oberts per camí.
- `work/depura/notes.json`: notes, `{clau: [{t, text, codi}]}`.
