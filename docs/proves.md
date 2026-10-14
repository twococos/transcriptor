# Fase 0 — Proves d'eines

> Data: 2026-10-14. Màquina: PC i7-6700 (4 nuclis / 8 fils), 16 GB, Windows 11 Home, **només CPU**.
> Python 3.11.17 instal·lat amb `uv` 0.13.1. Sense compilador C/C++ al sistema (ni MSVC ni gcc):
> si una dependència hagués de compilar, la instal·lació fallaria, que és justament la prova.
> Cada eina s'ha provat en un entorn virtual aïllat (`work/envs/<eina>`) per no barrejar conflictes de versions.
> Scripts de prova a [`proves/`](../proves/); resultats crus a `work/` (no versionat).

## Cançons de referència

| Clau | Cançó | BD | YouTube | Durada | To BD | Capo |
|---|---|---|---|---|---|---|
| `estaca` | L'estaca — Lluís Llach | id 110 | `J-fFsUFAnUc` | 2:25 | Am | 0 |
| `bondia` | Bon dia — Els Pets | id 111 | `XgwnYXOfIkk` | 4:35 | A | 0 |
| `gent` | La gent que estimo — Oques Grasses (amb Rita Payés) | id 112 | `yGO3UPPuVKs` | 4:00 | A | 1 |

**Nota sobre L'estaca**: el vídeo és la gravació original de 2:25 (2 estrofes). Inicialment el `content`
de la BD era el d'un directe amb 3 estrofes; el 2026-10-15 es va corregir a la BD perquè coincideixi amb
el vídeo. Les lletres de LRCLIB continuen sent totes de la versió llarga. La cançó és en **6/8 (o 12/8)**.

## Resum

| Etapa | Eina | Windows + uv sense compilar | Temps CPU (cançó de 4 min) | Qualitat | Veredicte |
|---|---|---|---|---|---|
| Descàrrega | yt-dlp + imageio-ffmpeg | ✅ | segons | — | ✅ |
| Separació | demucs `htdemucs` | ✅ | ~3 min | bona | ✅ CPU |
| Separació | demucs `htdemucs_ft` | ✅ | ~26 min | = htdemucs | ❌ massa lent |
| Separació | audio-separator Mel-RoFormer | ✅ (cal `ffmpeg` al PATH) | ~11 min | lleugerament millor | ✅ GPU |
| Ritme | Beat This! | ✅ | ~12 s | pulsacions bones; inicis de compàs irregulars | ✅ + postprocés |
| Acords | BTC (170 acords) | ✅ (codi de 2019, cal modernitzar-lo) | ~7 s | 99-100 % de la seqüència de la BD; detecta el capo | ✅ |
| Acords | Chordino (vamp) | ❌ cal compilar `vamp` | — | — | ❌ |
| Acords | ChordFormer | ❌ sense pesos públics | — | — | ❌ |
| Tonalitat | acords + Krumhansl | ✅ (numpy) | 0 s | 3/3 encerts | ✅ |
| Lletra (text) | LRCLIB | ✅ (HTTP) | segons | 3/3 trobades; temps poc fiables | ✅ només text |
| Lletra (ASR) | faster-whisper large-v3-turbo | ✅ (⚠ Smart App Control) | ~1,2 min | WER 0,17-0,23 | ✅ |
| Lletra (ASR) | faster-whisper large-v3 | ✅ | ~2 min | WER 0,14-0,26 | ❌ no millora |
| Alineació | stable-ts `align()` | ✅ | ~1,5 min | col·lapsa en cançons llargues | ❌ |
| Alineació | ASR → text (Needleman-Wunsch, nou) | ✅ (Python pur) | 0 s | mediana 0,17-0,40 s | ✅ |
| Alineació | WhisperX + wav2vec2 català | ✅ (torch 2.8, deps pesades) | ~1 min | precisa amb bones finestres | ✅ refinament opcional |

**Cost estimat per cançó de 4 min en aquest PC (CPU)**: htdemucs ~3 min + ASR turbo ~1,2 min + ritme i
acords ~20 s + transferència 0 s (+ WhisperX ~1 min opcional) ≈ **4,5-5,5 min**, és a dir, ~260-320
cançons/dia. Encaixa amb el pla (5-15 min).

## Detall per etapa

### Descàrrega: `yt-dlp` + `imageio-ffmpeg`

- **Windows/uv**: ✅ wheels pures. `imageio-ffmpeg` porta un `ffmpeg.exe` dins la wheel (v7.1), així
  no cal instal·lar ffmpeg a part. `yt-dlp[default]` inclou `yt-dlp-ejs`; amb `--js-runtimes node` resol
  els reptes JS de YouTube amb el Node que ja hi ha.
- **Resultat**: les 3 cançons baixades i convertides a WAV 44,1 kHz estèreo en pocs segons.
- Algunes eines (audio-separator, `whisper.load_audio` de stable-ts) criden l'executable `ffmpeg` pel
  PATH. Solució al pipeline: posar l'`ffmpeg.exe` portable en un directori propi i afegir-lo al PATH
  del procés, o bé passar-los l'àudio ja carregat com a array (el que fem a les proves).

### Separació de veu

| Eina | Model | Windows/uv | estaca (2:25) | bondia (4:35) | gent (4:00) | Temps real |
|---|---|---|---|---|---|---|
| `demucs` 4.1.0 | `htdemucs` | ✅ | 119 s | 195 s* | 192 s* | ~0,7-0,8× |
| `demucs` 4.1.0 | `htdemucs_ft` | ✅ | 959 s | — | — | ~6,6× |
| `audio-separator` 0.47 | Mel-RoFormer (Kim) | ✅ | 474 s | 752 s | 628 s | ~2,6-3,3× |

\* Mesurats mentre corrien proves lleugeres en paral·lel (BTC, Beat This!): una mica inflats.

- `demucs` 4.1.0 ja no fa servir `torchaudio` per llegir/escriure àudio, de manera que funciona amb
  torch 2.14 encara que `torchaudio` s'hagi quedat a la 2.11.
- `htdemucs_ft` és una bossa de 4 models: **~26 min per cançó de 4 min en aquesta CPU**. No és viable
  en CPU; queda per al perfil GPU. Vam aturar el lot després de L'estaca.
- `audio-separator` necessita l'executable `ffmpeg` al PATH (la primera execució va fallar per això).
- **Qualitat**. No tenim pistes de veu de referència; mesurem de dues maneres indirectes:
  1. *Fuita*: energia de la pista de veu fora dels trams cantats (segons l'ASR) respecte de la de dins
     ([`proves/fuita_veu.py`](../proves/fuita_veu.py)). Més negatiu = més net.
  2. *Efecte a la lletra*: WER de Whisper large-v3-turbo sobre cada pista de veu.

  | Cançó | Fuita htdemucs | Fuita Roformer | WER sobre htdemucs | WER sobre Roformer | WER sobre la mescla (sense separar) |
  |---|---|---|---|---|---|
  | estaca | −5,1 dB (`_ft`: −5,2) | −5,4 dB | 0,169 | — | 0,169 |
  | bondia | −10,0 dB | −12,7 dB | 0,226 | **0,183** | **1,000** (el VAD ho descarta tot) |
  | gent | −5,2 dB | −5,2 dB | 0,181 | 0,177 | 0,542 |

- Conclusions:
  - **La separació és imprescindible** per a la lletra en cançons amb banda. Només amb veu i guitarra
    (L'estaca) la mescla dona el mateix resultat.
  - `htdemucs_ft` no aporta res mesurable respecte d'`htdemucs` i és 8 vegades més lent.
  - Roformer és una mica més net i millora el WER de Bon dia, però és ~4 vegades més lent que
    htdemucs en CPU. **CPU: htdemucs. GPU: Roformer** (o quan la lletra s'hagi de transcriure sense text).

### Ritme: Beat This! (`beat-this` 1.1.0, checkpoint `final0`)

- **Windows/uv**: ✅ (només PyTorch, `soxr`, `einops`, `rotary-embedding-torch`). El postprocessador
  DBN opcional necessita madmom → no el fem servir (postprocessador `minimal`).
- **Temps**: 6-12 s d'inferència per cançó (+ ~0,5 s de càrrega). Negligible.

| Cançó | BPM (mediana) | Pulsacions/compàs | Observació |
|---|---|---|---|
| estaca | 200 | 3 (110 de 149 compassos) | Els acords canvien cada 6 pulsacions: encaixa amb el **6/8 / 12/8** real (negra amb punt ≈ 67): Beat This! compta corxeres i parteix el compàs en dos. |
| bondia | 125 | 4 (137 de 140) | Perfecte, 4/4 estable. |
| gent | 107 | 4 a la primera meitat, erràtic a la segona | Molts inicis de compàs falsos (compassos d'1, 5, 7…). Cal regularitzar. |

- Conclusió: les **pulsacions** són fiables; els **inicis de compàs** necessiten postprocés (Fase 2):
  imposar un compàs constant per trams (moda de pulsacions/compàs) i triar la fase per votació, en
  lloc de confiar en cada inici de compàs predit.

### Acords

#### BTC (ISMIR19, vocabulari gran de 170 acords) — ✅ escollit

- No és un paquet pip: és un repo (llicència MIT) amb els pesos inclosos (12 MB). Dependències:
  `torch`, `librosa`, `mir_eval`, `pyyaml`. **Windows/uv**: ✅ (numba/llvmlite/scipy amb wheels).
- Codi de 2019 amb rovell: `yaml.load()` sense `Loader`, àlies `np.float`/`np.int` eliminats i
  `torch.load()` necessita `weights_only=False`. A la prova ho apedacem des de fora
  ([`proves/acords_btc.py`](../proves/acords_btc.py)); a la Fase 1 cal **incorporar el model al repo**
  (només `btc_model.py` + `transformer_modules.py` + pesos) i modernitzar-lo.
- **Temps**: ~7 s per cançó (5-6 s de CQT amb librosa + <1 s d'inferència).
- **Qualitat** (seqüència col·lapsada a nivell `majmin`, Needleman-Wunsch provant els 12 transports;
  script [`proves/compara_acords.py`](../proves/compara_acords.py)). Segments < 0,5 s descartats:

| Cançó | Recuperat de la BD | Correcte del predit | Transport detectat | To estimat | To BD |
|---|---|---|---|---|---|
| estaca | 99 % (68/69) | 86 % | 0 | Am | Am |
| bondia | 100 % (94/94) | 67 % | 0 | A | A |
| gent | 100 % (82/82) | 89 % | **+1** | **A#** | A, capo 1 ✅ |

  - L'estaca: amb el `content` antic (directe de 3 estrofes) només en recuperava el 73 %; amb la BD
    corregida perquè coincideixi amb el vídeo, el 99 %. Els errors restants són canvis curts E/E7 de més.
  - Bon dia: recupera tota la seqüència, però hi afegeix acords (sèptimes, inversions i canvis curts).
    Això ho ha de netejar el postprocés de la Fase 2 (quantitzar a pulsacions, mínim 1 pulsació).
  - La gent que estimo: detecta que sona un semitò amunt (A#), cosa coherent amb el capo 1 de la BD.
    Aquest transport és exactament el que necessitarem per suggerir cejilla.
- Variant **sobre l'acompanyament sense veu** (`no_vocals` de htdemucs): resultats pràcticament idèntics
  (estaca 100 % recuperat; bondia 98 % recuperat; gent igual). No aporta prou per justificar
  que els acords esperin la separació: es poden calcular sobre la mescla en paral·lel.
- **Tonalitat a partir dels acords** (histograma ponderat per durada + Krumhansl-Kessler): encerta les 3
  (correlació 0,82 / 0,87 / 0,95). Confirma que no ens cal Essentia.

#### Chordino (NNLS-Chroma via vamp) — ❌ descartat

- El paquet `vamp` de PyPI només té wheels de Windows per a **Python 2.7 (win32)**. Per a Python 3 cal
  compilar l'extensió C → descartat per la regla de Fase 0.
- Alternativa no provada: l'executable `sonic-annotator` + la DLL del plugin. Funcionaria sense compilar,
  però afegeix binaris externs fora d'`uv`. Amb BTC tan bo, no val la pena.

#### ChordFormer — ❌ descartat

- Només hi ha el paper (arXiv 2502.11840). No hi ha codi ni pesos públics.

### Lletra

#### Fonts de text: LRCLIB

- Les 3 cançons hi són, amb lletra **sincronitzada per línia** (no per paraula).
- L'API respon sovint **503 ServerOverloaded**: amb reintents i espera creixent (5 s, 10 s…) funciona
  al primer o segon intent. El client ho ha de gestionar.
- **Metadades poc fiables**: les 19 entrades de L'estaca comparteixen el mateix LRC (versió de ~4:11),
  incloses les que declaren una durada de 143-144 s. **Cal validar que l'últim temps de l'LRC sigui ≤
  durada de l'àudio** i, si no, fer servir només el text (alineació) i no els temps.
- **Temps desplaçats**: comparant amb l'ASR i l'alineació, l'LRC de Bon dia va **~2,5 s endarrerit**
  respecte del vídeo i el de La gent que estimo ~0,9 s. Conclusió: de LRCLIB en volem **el text i el tall
  de línies**; els temps els calculem nosaltres.

#### ASR: `faster-whisper` 1.2.1 (CTranslate2, int8 en CPU)

- **Windows/uv**: ✅ wheels. Però vegeu [Smart App Control](#risc-smart-app-control).
- Paràmetres: `language="ca"`, `word_timestamps=True`, `vad_filter=True`, `beam_size=5`,
  `condition_on_previous_text=False`, sobre la veu d'htdemucs.
- WER contra la lletra **realment cantada** (L'estaca: estrofes 1-2 i tornades de la BD; Bon dia i La
  gent: text de l'LRC, que inclou les repeticions). Normalització: minúscules, sense puntuació.

| Model | estaca | bondia | gent | Temps (estaca / bondia / gent) |
|---|---|---|---|---|
| large-v3-turbo | 0,169 | 0,226 | 0,181 | 62 s / 78 s / 65 s |
| large-v3 | 0,137 | 0,257 | 0,200 | 104 s / 136 s / 116 s |

- **large-v3-turbo guanya**: WER equivalent (millor a 2 de 3) i ~1,7 vegades més ràpid. El pla preveia
  4-10 min per a large-v3 int8; en realitat, ~2 min. Turbo: **~1,2 min per cançó de 4 min**.
- Errors típics, fonètics: "Sobre un feixugues padallant", "grans gafarades del cuol", "Nens d'esclà, no
  l'opi xundegat". Sense text de referència la lletra sempre caldrà revisar-la: confirma l'estratègia híbrida.

#### Alineació forçada: `stable-ts` 2.19.1 (Whisper d'OpenAI, PyTorch)

- **Windows/uv**: ✅. `stable-ts` i `openai-whisper` només es distribueixen com a sdist, però són
  Python pur: `uv` els empaqueta sense compilador.
- Hem provat `align()` amb el backend faster-whisper large-v3-turbo (el model ja descarregat). Els models
  d'OpenAI (`medium`, `large-v3-turbo` .pt) eren 3 GB més de descàrrega i ho vam deixar córrer.
- **Temps**: 56 s / 91 s / 110 s.
- **Qualitat: dolenta en cançons llargues amb banda**. A La gent que estimo l'alineació col·lapsa: totes
  les paraules de la primera meitat queden a 10,0 s i la resta s'amuntega fins als 97 s (la cançó en fa
  240). A Bon dia comença bé, però l'error d'inici de línia és d'1,1 s de mediana (44 % < 1 s).
- **Descartat** com a alineador principal.

#### Alternativa nova: transferir els temps de l'ASR al text conegut

No era al pla; ha sorgit de les proves ([`proves/transfereix_temps.py`](../proves/transfereix_temps.py)).
Alineem les paraules del text conegut amb les de l'ASR (Needleman-Wunsch amb coincidència aproximada per
similitud de caràcters ≥ 0,6), copiem els temps de les parelles i interpolem la resta. Cost: zero (l'ASR
ja l'hem fet) i robust contra els col·lapses.

- Paraules aparellades: 164/183 (estaca), 204/230 (bondia), 224/260 (gent): 87-90 %.
- Error d'inici de línia contra l'LRC, un cop restat el seu desplaçament constant: mediana **0,17 s** a
  Bon dia (83 % < 0,5 s, 90 % < 1 s) i **0,40 s** a La gent (65 % < 0,5 s, 84 % < 1 s).

Avaluació: [`proves/avalua_alineacio.py`](../proves/avalua_alineacio.py) compara la primera paraula de
cada línia amb el temps de l'LRC. L'LRC no és una veritat perfecta (té el seu propi error), però serveix.

#### Alineació forçada: WhisperX 3.8.6 + `softcatala/wav2vec2-large-xlsr-catala`

- **Windows/uv**: ✅, però fixa **torch 2.8** (no la 2.14) i arrossega `pyannote-audio`, `pytorch-lightning`,
  `transformers`… La instal·lació va trigar >10 min. `torchcodec` no carrega (li falten les DLL d'FFmpeg),
  però `whisperx` importa igualment i l'alineació no en depèn si li passem l'àudio carregat.
- WhisperX no té model d'alineació català per defecte; fem servir el wav2vec2 de Softcatalà.
- Cal passar-li **segments** (finestres de temps amb el text de cada línia). Hem fet servir les línies de
  l'LRC (Bon dia, corregit −2,5 s) i, per a L'estaca, línies derivades de l'alineació de stable-ts.
- **Temps**: 52 s / 48 s / 57 s d'alineació, + 10-14 s de càrrega. 0 paraules sense temps; dona
  confiança per paraula.
- **Qualitat**: a Bon dia, 78 % de línies < 0,5 s i 95 % < 1 s. A La gent, 98 % < 0,5 s, però **aquesta
  xifra és circular**: les finestres eren el mateix LRC amb què l'avaluem. A L'estaca coincideix en
  ±0,3 s amb la transferència des de l'ASR.
- Conclusió: l'alineació CTC és precisa **si les finestres són bones**. La transferència des de l'ASR
  pot proporcionar aquestes finestres sense dependre de LRCLIB.
- Detalls a tenir en compte:
  - `transformers` llença un fil que baixa la versió *safetensors* del model (1,2 GB més) i el procés
    no surt fins que acaba. A producció: preparar el model una vegada i carregar-lo en mode offline
    (`HF_HUB_OFFLINE=1`).
  - El procés ocupa ~2,3 GB de RAM.

## Risc: Smart App Control

El PC té **Smart App Control** activat (`VerifiedAndReputablePolicyState = 1`). La primera vegada que
es va carregar `ctranslate2` (dependència de faster-whisper), Windows la va bloquejar:

```
ImportError: DLL load failed while importing _ext: Una directiva de Control de aplicaciones bloqueó este archivo.
```

`ctranslate2.dll` i `_ext.cp311-win_amd64.pyd` **no estan signades**. Uns minuts després la mateixa
importació va funcionar (Smart App Control consulta la reputació al núvol). No l'hem desactivat: a
Windows 11 desactivar-lo és irreversible sense reinstal·lar.

Implicacions per a l'app de col·laboradors (Fase 7): molts Windows 11 nous el porten activat. Cal
(a) detectar el bloqueig i mostrar un missatge entenedor + reintentar, (b) preferir dependències amb
binaris signats o amb molta difusió, i (c) tenir present que la signatura de codi de l'instal·lador no
cobreix les DLL de tercers que baixa `uv`.

## Descàrregues de models

A aquesta connexió, Hugging Face va a ~0,7-1 MB/s sense token. Mides aproximades: Whisper
large-v3-turbo 1,6 GB, large-v3 3 GB, wav2vec2 català 1,2 GB, htdemucs 80 MB, Beat This! 80 MB,
BTC 12 MB (al repo). Per a la Fase 7 cal mostrar progrés de descàrrega i permetre reprendre-la.

## Elecció provisional de backends

| Etapa | Perfil CPU | Perfil GPU |
|---|---|---|
| Separació | `htdemucs` (demucs) | Mel-RoFormer (audio-separator) |
| Ritme | Beat This! `final0` + regularització pròpia del compàs | igual |
| Acords | BTC vocabulari gran, sobre la mescla (no cal esperar la separació) | igual |
| Tonalitat | histograma d'acords + Krumhansl; el transport respecte de la BD dona la cejilla | igual |
| Text de la lletra | usuari > BD > LRCLIB (només text i línies, amb reintents per als 503) | igual |
| ASR | faster-whisper large-v3-turbo int8, sobre la veu separada | large-v3-turbo float16 |
| Temps per paraula | transferència ASR → text conegut; WhisperX + wav2vec2 català com a refinament opcional | WhisperX sempre |

Canvis respecte del pla que proposo:

1. **Treure stable-ts** i afegir l'**ASR sempre**, també quan tenim el text: serveix per transferir els
   temps al text conegut (l'alineació "pura" de stable-ts col·lapsa).
2. **WhisperX com a refinament opcional**, en un entorn propi o amb dependències controlades: fixa
   torch 2.8 i arrossega pyannote. Abans de la Fase 1 cal decidir si val la pena dins el mateix `uv sync`
   o si fem servir directament `transformers` + el wav2vec2 de Softcatalà amb un alineador CTC propi
   (`torchaudio.functional.forced_align`, o el nostre si torchaudio continua quedant-se enrere).
3. **Acords sobre la mescla**, en paral·lel a la separació.
4. Postprocés de ritme a la Fase 2: el compàs no es pot llegir directament dels inicis de compàs de
   Beat This! (La gent que estimo).

## Preguntes obertes

- ~~Compàs de L'estaca~~: resolt, és 6/8 (o 12/8). Cas de prova per a la regularització del compàs
  (Fase 2): cal detectar que Beat This! compta corxeres i agrupar-les de 6 en 6.
- ~~Versió de L'estaca~~: resolt, la BD ja té les 2 estrofes del vídeo.
- L'enllaç de La gent que estimo és el videoclip oficial amb Rita Payés: confirmar que l'àudio és igual
  que el de l'àlbum (els acords i la lletra hi encaixen bé, i l'LRC amb un desplaçament de ~0,9 s).

## Com reproduir-ho

```bash
# Entorns (un per eina), p. ex.:
uv venv -p 3.11 work/envs/btc
VIRTUAL_ENV=work/envs/btc uv pip install --index-url https://download.pytorch.org/whl/cpu \
  --extra-index-url https://pypi.org/simple --index-strategy unsafe-best-match torch librosa mir_eval pyyaml soundfile
# Lots de proves (escriuen temps a work/proves/temps.tsv):
proves/lot_demucs.sh; proves/lot_principal.sh; proves/lot_lletra.sh; proves/lot_roformer.sh
```

Els scripts esperen l'àudio a `work/audio/{estaca,bondia,gent}.wav`, la lletra a `work/lletres/` i les
referències de la BD a `work/ref/` (extretes en mode només lectura de `data/canconer.db` del canconer).
