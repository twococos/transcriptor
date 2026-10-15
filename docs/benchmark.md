# Benchmark i qualitat (Fases 4-5)

> 2026-10-15. 108 cançons de la BD del canconer (19 publicades + 89 esborranys) amb `youtubeUrl`,
> processades al PC (i7-6700, només CPU). Taula completa per cançó: [benchmark_resultats.md](benchmark_resultats.md).
> Reproduir: `tx bench --nom <nom>` (o `--nomes-postproces` per iterar sobre la cache en segons).

## Com es mesura

Les referències de la BD també tenen errors: és **concordança**, no veritat absoluta. La lletra de
la BD es fa servir com a text conegut (mode "db"), com quan es reprocessi una cançó existent.

| Mètrica | Què mesura |
|---|---|
| Acords majmin | Seqüència d'acords col·lapsant repeticions, alineada amb Needleman-Wunsch provant els 12 transports (la gravació pot estar en un altre to). *Recuperat* = part de la BD trobada; *correcte* = part del predit que és a la BD. |
| Acords sevenths | Igual, distingint 7, maj7, m7 i dim. |
| Col·locació | Dels acords de les línies de lletra de la BD, quants cauen **a la mateixa paraula**. |
| Estructura | Per a cada línia de lletra, si el tipus de secció (Estrofa, Tornada…) coincideix. |
| To | Comparat en "formes" (to predit menys la cejilla suggerida, contra el to de la BD amb el transport detectat). |
| WER | Error de paraula de l'ASR contra la lletra de la BD. Orientatiu: la BD no sempre escriu les repeticions. |

## Resultats

| | Totes (108) | Referències sense problemes (90) | Publicades (19) |
|---|---|---|---|
| Acords majmin recuperat / correcte | 90,1 % / 63,4 % | 89,1 % / 67,7 % | **94,1 %** / 64,1 % |
| Acords sevenths recuperat / correcte | 85,2 % / 60,0 % | 84,4 % / 64,3 % | 89,5 % / 61,7 % |
| Col·locació | 46,3 % | 47,0 % | 50,9 % |
| Estructura | 73,9 % | 77,0 % | 81,9 % |
| To vs to dels acords de la BD | 98/108 | 83/90 | 18/19 |
| To vs camp `key` de la BD | 77/108 | 64/90 | 12/19 |
| WER de l'ASR | 0,38 | 0,38 | 0,35 |

- **Objectiu del pla** (≥80 % de concordança d'acords majmin): **assolit**, amb un 90 % de mitjana. 89 de
  108 cançons hi arriben.
- La "precisió" més baixa (63 %) vol dir que **posem més acords que la BD**: acords de pas,
  inversions i canvis que la BD simplifica. Endurir el suavitzat la puja, però a costa del recall
  (penalització 8: 81,5 % / 70,2 %). Hem preferit no perdre acords; la revisió humana en treu.
- **Temps** (passada completa, CPU): mediana de **226 s per cançó** (p90: 293 s), uns 380 al dia.
  Memòria màxima del procés: **2,4 GB**, de manera que hi cap al servidor.
- **Format**: els 108 `content` generats passen la validació amb el `parse`/`serialize` real del canconer
  (`tools/valida_content.mts`), noms de secció de `SECTION_TYPES` i acords vàlids.
- Les 3 cançons de referència: L'estaca 100 % acords / estructura 100 % (6/8 detectat), Bon dia 100 % /
  81 %, La gent que estimo 98 % / 100 % (detecta el capo 1).

## Què s'ha ajustat amb el benchmark (Fase 5)

Cada canvi s'ha mesurat amb `proves/escombrat.py`, que refà només el postprocés sobre la cache.

| Canvi | Efecte |
|---|---|
| Idioma de l'ASR deduït del text conegut i detecció de Whisper sobre 6 trossos | "Esperança" es transcrivia en anglès (WER 1,34 → 0,82, que és un directe amb presentació parlada) |
| Expansió de les marques "x2", "bis", "(x3)" de la BD (78 casos) | El text quadra amb el que es canta |
| Col·locació: paraula amb l'inici més proper, avançant l'acord 0,1 s, penalització 2,5 a les paraules posteriors | 42 % → 55 % (amb 26 cançons); es manté amb 60 |
| Pre-tornada (línies inicials d'una tornada que es repeteixen menys) | "A la deriva": estructura 75 % → 88 % |
| Pont per ordre d'acords diferent (≥60 % de bigrames nous) | Lleuger guany |
| Paraules interpolades a ritme de parla; buits de >6 s dins d'una línia | Les línies ja no s'estiren sobre els trams instrumentals (Bon dia) |
| Pes de les sèptimes 0,6 → 0,3 | Lleuger guany al nivell sevenths |
| To: estimador funcional (graus diatònics + tònica al principi i al final + cadències) en lloc de Krumhansl | 39 → 43 exactes sobre 62 |

Provat i **descartat**:
- **Afinament CTC** amb wav2vec2 català (`afinar_ctc: true`): la col·locació no millora (53 → 50 %) i
  costa 1-2 min per cançó. La BD no posa els acords amb precisió de mil·lisegons.
- **Vocabulari majmin** (sense sèptimes): el mateix resultat i pitjor to.
- Llindars més baixos de posició del pont: empitjoren el conjunt.

## Limitacions conegudes

- **Col·locació (~50 %)**: el 55 % dels acords cauen a la paraula exacta i un 14 % una paraula més
  tard. Una part és subjectiva: la BD no és consistent a l'hora de repetir acords a l'inici de línia,
  ni sobre si l'acord va a la síl·laba o a la paraula.
- **Estructura**: depèn de les repeticions de la lletra. Falla en cançons sense repeticions clares o
  amb seccions que la BD anomena de manera subjectiva (Pre-tornada vs Estrofa).
- **Lletra només amb ASR** (sense text): WER ~0,2-0,4, amb errors fonètics. Cal revisió.
- **VAD de Whisper**: pot ometre veu molt fluixa (`vad_llindar` configurable, no ajustat al benchmark
  perquè obliga a refer l'ASR de totes les cançons).

## Problemes de dades trobats a la BD del canconer

Per revisar quan convingui (no s'ha tocat res del canconer):

1. **El camp `key` sovint és l'arrel del primer acord** (com fan els importadors), no el to real. Ex.:
   "Rock and Roll" (C#, però el to és F#; C#7 n'és el V7), "Inevitable" (A → D), "Amagada primavera"
   (F → C), "In the night" (Cm → Gm). El nostre to discrepa del `key` en 31 de 108 cançons, però
   coincideix amb el to que es dedueix dels acords de la mateixa BD en 98 de 108.
2. **Vídeos d'una altra cançó**: id 20 "Que tot et vagi bé" → el vídeo és "Pren el carrer"; id 22
   "Som foc" → "Quan cau el sol". El transcriptor ara ho avisa ("només el 8 % de la lletra coincideix").
3. **Mateix vídeo a dues cançons**: 17 "Quan calla la ciutat" i 21 "Si sabessis"; 19 "Quan tot
   s'enlaira" i 24 "Somriurem".
4. **Idioma (`language`) erroni** en ~19 cançons. Ex.: 112 "La gent que estimo" (`es`, és en català);
   moltes de Stay Homas en anglès o castellà marcades com a `ca`; 106 "Si Vens" (`fr`, és en català).
5. **Lletra d'una altra versió** que el vídeo: "Les merdes" (el vídeo del confinament comença per la
   tornada i no té l'estrofa 1).
6. **Sense seccions**: 102 "Un Lloc", 107 "Aixi I Tot", 108 "L'univers", 109 "Per A Tu" (i 58, 72, 73,
   82, 100 amb una sola secció).
7. **Notació no estàndard** dins del content: acords amb fletxa ("E→A", "C→D"), solfeig com a text
   ("FA# SI (x8)"), i restes d'HTML a la lletra ("</em>", p. ex. a 3, 12 i 49).
8. Vídeos que YouTube no deixa baixar (403 persistent): 24, 42, 107.
