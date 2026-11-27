# Depurador i visor (`tx depura`, el play de l'app i l'admin del canconer)

Eina per veure què fa cada pas del postprocés i per trobar els problemes habituals de les
transcripcions. Se sincronitza amb YouTube (o amb l'àudio local) com el visor. És la mateixa
pàgina (`src/transcriptor/depura/depura.html`) a tres llocs:

| On | Com s'obre | Llista | D'on surt la traça |
|---|---|---|---|
| L'admin del canconer | Botó ▶ d'una transcripció (pestanya Transcripcions) | Les transcripcions de la web | La que hi va pujar el worker amb el resultat |
| L'app del transcriptor | Botó ▶ d'una cançó feta | Les caches d'aquest ordinador | Es calcula amb les dades crues de la cache |
| `tx depura` (desenvolupament) | `uv run tx depura [clau o analysis.json]` | El banc i les caches locals | Es calcula amb el codi actual |

```
uv run tx depura                          # obre http://localhost:8766/ amb la llista
uv run tx depura out/XgwnYXOfIkk          # un analysis.json (o el directori que el conté)
uv run tx depura 100                      # una cançó del banc
```

Executa `tx depura` des del directori del transcriptor. El banc és a `work/bench/` i la cache a
`work/cache/` (o a `TX_HOME`). La pestanya Banc només surt si hi ha el banc.

## Al canconer

**La pàgina:**
- És `public/depurador/index.html` (a `/depurador`), una còpia de `depura.html`.
- Després de canviar-la, `uv run python tools/copia_depurador.py` la copia al canconer
  (`../guitarreopuntcat`). Cal fer-ne commit als dos repositoris.

**La traça:**
- El worker (0.1.17+) puja la traça de cada feina amb el resultat. És el camp `trace` del resultat:
  un JSON en gzip, en base64, d'uns 40 KB.
- El canconer la desa a `song_analysis_traces` (migració 0012).
- Si un worker antic actualitza la cançó sense traça, la que hi havia s'esborra, perquè ja no és de
  l'anàlisi vigent.

**Anàlisis sense traça:**
- Les anàlisis d'abans no en tenen. El depurador només en mostra el resultat (acords, lletra,
  seccions i el content), sense passos intermedis.
- «Reprocessa amb un worker» encua una actualització de la cançó al principi de la cua. Quan un
  worker l'acaba, en recarregar la cançó ja hi ha la traça.

**Comparacions:**
- Es compara amb el que hi ha ara a la web («Web ara»): l'anàlisi publicada i el content de la
  cançó, que potser s'ha editat a mà després de l'anàlisi.
- Si quan es va fer la feina el content l'havia escrit una persona, la traça ja porta la
  referència col·locada al temps, com al banc.

**Notes:** es desen al navegador (localStorage).

**API**, només per a admins:
- `GET /api/admin/depurador/songs?q=&limit=`: la llista de transcripcions.
- `GET /api/admin/depurador/songs/{id}`: la cançó, l'anàlisi compacta, el content del transcriptor i
  `trace`.
- `POST /api/admin/depurador/songs/{id}/reprocess`: encua l'actualització.

## En local: d'on surten les cançons

| Clau | Origen | Com es refà el postprocés | Referència |
|---|---|---|---|
| `banc-<id>` | `work/bench/dataset.jsonl` | Com `tx bench`, amb la cache de `work/cache` | content de la BD (còpia del banc) |
| `local-w-<cache>` | la cache de `TX_HOME` (`work/cache`; a l'app, la de l'app) | Amb les dades crues de la cache | — |
| `local-a-<cache>` | la cache de l'app (`%LOCALAPPDATA%\Transcriptor\dades\cache`), si no és la de `TX_HOME` | Amb les dades crues de la cache | — |
| `fitxer-<hash>` | un `analysis.json` sense cache local | No es refà: només es mostra l'anàlisi | — |

**`local-*`:**
- El títol, l'artista i les tabs afegides surten de la cerca de tabs de la cache, perquè es
  reaprofitin les tabs baixades.
- Si a l'app (`fetes/`) o a `out/` hi ha l'anàlisi que es va fer de la mateixa cançó, es compara.
- El play de l'app obre la cançó a partir del directori de la feta (`servidor.clau_de`). Si en
  queda la cache, és la clau `local-…`; si no, `fitxer-…`.

Mai es calcula cap etapa cara (separació, Beat This, BTC, Whisper): només es fan servir dades crues
ja fetes. Amb les tabs sí: si els paràmetres de la cerca no coincideixen, es tornen a buscar a
internet, com faria el worker.

## Com funciona

Quan s'obre una cançó en local:
- El servidor executa `python -m transcriptor.depura.genera <clau>` en un subprocés.
- Desa la traça a `work/depura/<clau>/traca-<codi>.json`, on `codi` és un hash del codi font.
- Si el codi no ha canviat, la traça es reaprofita.
- Si has editat el postprocés, en obrir la cançó es recalcula sola (~2–20 s), sense reiniciar el
  servidor.
- «Recalcula» la força.

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

`genera.completa` hi afegeix les dades següents. També el fa servir el worker, des de
`per_al_canconer`.
- el content sense tabs (segona passada amb `fonts_acords=False`);
- la referència col·locada al temps;
- les mètriques del banc respecte de la referència;
- les rodes i quasi-rodes de cada zona instrumental (`rodes.quasi_rodes`).

## Vistes

**Llista:**
- Al canconer, les transcripcions, amb cerca per títol, artista o id.
- En local, dues pestanyes:
  - **Banc**: les mètriques d'un run i la diferència respecte d'un altre. «Problemes de tot el
    banc» compta els avisos de totes les cançons.
  - **Caches locals**: les de l'app i les de `tx run`, sense les del banc.

**Reproductor:**
- El vídeo de YouTube, amb el mateix suavitzador i desplaçament que el visor. També pot fer servir
  l'àudio local: el del banc, o `audio.wav` de la cache si encara hi és.
- Velocitat, clic de pulsació i acords sonors programats amb antelació.
- En directe: compàs, acord actual i següent, secció i línia amb la paraula que sona.

**Línia de temps:**
- Files en grups que es pleguen. Plegat, només hi ha el resultat; desplegat, també els passos,
  indentats:
  - Compassos › pulsacions crues;
  - BTC: plegada, l'acord més probable; desplegada, els tres;
  - Acords finals › acords d'àudio, sense tabs;
  - Tabs: consens › una fila per tab;
  - Referència › seccions; l'anàlisi comparada › seccions;
  - Lletra alineada › Whisper cru;
  - Seccions finals › 1 detectades, 2 amb les tabs;
  - Notes.
- La casella de l'esquerra amaga la fila. Les amagades surten a sota per tornar-les a mostrar, una a
  una o totes.
- Passant per sobre del nom d'una fila es veu què és.
- El panell de la dreta és el detall del moment que sona (o d'on has clicat, si no sona). Hi ha les
  notes i «Copia informe», un markdown per enganxar al xat.
- Controls:
  - Clic: hi salta.
  - Roda: zoom.
  - Arrossegar: desplaça.
  - Majúscules + arrossegar: bucle.
  - Espai: reprodueix.
  - Fletxes: compàs anterior / següent.
  - C: clic.
  - A: acords.

**Content:** dos contents costat a costat, aparellats per lletra.
- Es pot triar entre: referència, anàlisi comparada («Web ara» al canconer), sense tabs, estructura
  detectada, seccions de les tabs i final. Passant per sobre de cada opció es veu què és.
- Els acords es comparen al so (major/menor) i a la mateixa paraula.
- Mentre sona, es veu com al reproductor de la web:
  - la línia que sona, marcada als dos costats;
  - un cursor que avança per la lletra, paraula a paraula;
  - l'acord que sona.
- Les línies sense lletra aparellada (acords, instrumentals) es reparteixen entre les del costat,
  de manera aproximada.
- El content es desplaça sol fins que fas scroll a mà.

**Fonts:**
- Les tabs en pestanyes, al mateix lloc. En canviar de pestanya es conserva el scroll, per
  comparar-les.
- Cada acord es pinta segons si l'àudio el permet, amb el pes, l'encaix i el motiu de descart.

**Seccions:** la taula de costos de `quadra`, les cues absorbides i les rodes / quasi-rodes.

**Lletra i ritme:** correccions de Whisper i de pulsacions, línies descartades, paraules dubtoses
i la corba de tempo.

**Problemes:** avisos automàtics amb enllaç al temps:
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

## Fitxers (en local)

- `work/depura/<clau>/traca-<codi>.json`: traces.
- `work/depura/cache/<clau>/`: cache de proves, perquè no es toqui la de l'app ni la del banc.
- `work/depura/fitxers.json`: els `analysis.json` oberts per camí.
- `work/depura/notes.json`: notes, `{clau: [{t, text, codi}]}`.
