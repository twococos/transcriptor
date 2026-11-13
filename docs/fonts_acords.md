# Fonts d'acords externes (0.1.14)

El transcriptor contrasta els acords i les seccions de l'anàlisi amb tabs d'internet, com ja fa amb
la lletra (LRCLIB). Codi a `src/transcriptor/fonts/` i `src/transcriptor/stages/chords_source.py`.

## Flux

1. **Cerca** (`stages/chords_source.obte`, en un fil mentre treballen els models). Es busca la cançó
   per títol i artista a cada lloc (`fonts/llocs/*.py`) i se'n baixen les versions que hi quadren.
   El resultat es desa a la cache (`chords_source.json`) i viatja dins les dades crues (`paquet.py`,
   camp `fonts`), així que una feina `update` no torna a baixar res.

   | Lloc | Com | Notes |
   |---|---|---|
   | Ultimate Guitar | navegador sense finestra (Edge/Chrome del sistema per DevTools, `fonts/navegador.py`) | fins a 3 versions, amb valoració i vots |
   | LaCuerda | `busca.php` + pàgina de la cançó | versions; sense valoració a l'HTML |
   | GuitarTuna | llistat d'artistes per lletra → pàgina de l'artista | només artistes de la primera pàgina |
   | acordscatala | pàgina de l'artista | només si l'idioma és català |
   | Cifra Club | URL per slug | Akamai respon 403: avui no troba res |

   Les URL afegides a mà a l'admin es baixen sempre; les descartades, mai. Si el content de la BD
   l'ha escrit una persona, també és una font («bd»).
2. **Format comú** (`fonts/normalitza.py`). Cada pàgina es converteix al format `content` del
   canconer. Es normalitzen els acords (solfeig, bemolls, sufixos, baixos) i les seccions
   (sinònims en català, castellà, anglès i portuguès), i es despleguen les repeticions: `x2`, seccions
   citades sense contingut, i estrofes sense acords que hereten els de l'anterior.
3. **Alineació amb l'àudio** (`fonts/alinea.py`). La lletra de la tab s'aparella amb les paraules de
   l'anàlisi, i cada acord s'ancora a la seva síl·laba. Una programació dinàmica sobre les pulsacions
   decideix on comença exactament cada acord. Una línia de lletra sense acords no opina.
4. **Consens** (`fonts/consens.py`). Cada tab vota a cada pulsació amb un pes:

   pes = prior del lloc × vots × encaix amb l'àudio × encaix local × àncora

   Les còpies (mateixes línies amb els acords a les mateixes columnes) voten com una sola font. Els
   vots se sumen a les log-probabilitats de BTC i es torna a passar el Viterbi per compàs. Finalment
   s'adopta la grafia de les fonts (G/B, Cadd9) on la sostenen.
5. **Seccions** (`fonts/seccions.py`). Cada tab vota on comença cada secció i de quin tipus és, i
   `structure.detecta` vota com una font més. Després `postprocess/seccions.quadra` quadra les
   fronteres amb el compàs com abans.

Sense cap tab vàlida, el resultat és exactament el de l'àudio sol.

## Sortida

- `SongAnalysis.chord_sources`: les tabs trobades, amb `site`, `url`, `rating`, `votes`, `manual`,
  `fit` (fracció d'acords que l'àudio admet), `matched` (lletra aparellada), `weight` (0 =
  descartada), `group` (còpies) i `used`. Al format compacte és opcional.
- `stats.checks.chords`: `trobades`, `valides`, `grups`, `confirmats`, `substituits`, `afegits`,
  `trets`, `canvis_inici`, `linies_seccio_canviada`.
- A cada acord, `raw` és l'etiqueta de BTC i `label` la grafia final.

## Camps nous de la feina (`claim`)

- `chord_source_urls`: URL afegides a mà.
- `chord_source_blocked`: URL descartades.
- `song_content_human`: el content de la cançó no és el que va escriure el transcriptor.

## Eines

- `tools/revisa_fonts.py --banc [N]`: cobertura i concordança de les tabs amb la BD i amb l'anàlisi,
  sense tocar cap resultat. `tools/revisa_fonts.py <id>` dona el detall d'una cançó.
- `tools/compara_bench.py <abans> <després>`: compara dues execucions de `tx bench`.
- `Config.fonts_acords = False` desactiva tot el sistema.
