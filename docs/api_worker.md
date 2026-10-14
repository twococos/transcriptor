# Proposta de protocol worker ↔ canconer

> Estat: **proposta per discutir a la Fase 6**. El client (`src/transcriptor/worker.py`) ja
> l'implementa i té tests contra un servidor simulat (`tests/test_worker.py`). Res d'això existeix
> encara al canconer.

Tot són peticions **sortints** del worker (HTTPS, JSON). Autenticació amb un token per worker:
`Authorization: Bearer <token>`. El canconer només en desa el hash (taula `transcription_workers`).

## Respostes comunes

| Codi | Significat | Què fa el worker |
|---|---|---|
| 401 | Token desconegut o revocat | S'atura i ho mostra (codi de sortida 2) |
| 426 | Versió massa antiga. Cos: `{"min_version": "0.3.0"}` | S'atura i demana actualitzar (codi 3; l'app s'autoactualitza) |
| 5xx / xarxa | Error temporal | Reintenta amb espera creixent (30 s → 5 min) |

## `POST /api/transcriber/claim`

Demana la següent feina. L'API l'assigna de forma atòmica (transacció de better-sqlite3) amb un
*lease*: si el worker no envia heartbeats, la feina torna a la cua quan caduca.

Petició:
```json
{ "worker": "PC-Coco", "app_version": "0.1.0",
  "device": { "type": "cpu", "name": "Intel i7-6700", "vram_gb": 0 } }
```
Resposta `204`: no hi ha feina. Resposta `200`:
```json
{ "job": {
    "id": 42,
    "source_url": "https://www.youtube.com/watch?v=XgwnYXOfIkk",
    "title": "Bon dia", "artist": "Els Pets",
    "language": "ca",
    "lyrics_text": null,
    "song_content": "<sec>Estrofa 1</sec>…",
    "lease_seconds": 600 } }
```
- `lyrics_text`: lletra enganxada per l'admin en encuar (opcional, té prioritat).
- `song_content`: `content` actual si es reprocessa una cançó existent (`song_id`); el worker en fa
  servir la lletra (font "db").
- `language`: opcional; si és null, l'idioma el detecta Whisper. **L'idioma de la BD no sempre és
  correcte** (p. ex. "La gent que estimo" hi consta com a `es`).

## `POST /api/transcriber/jobs/{id}/heartbeat`

Cos buit. Cada `lease_seconds / 3`. Allarga el lease. `404`/`409`/`410` = la feina ja no és d'aquest
worker (s'ha reassignat): el worker abandona el resultat.

## `POST /api/transcriber/jobs/{id}/result`

```json
{ "proposal": { "title": "…", "artist": "…", "key": "A", "capo": 1, "language": "ca",
                "tags": "", "content": "<sec>…", "youtubeUrl": "…" },
  "analysis": { "version": 1, "source": {…}, "key": {…}, "tempo": {…}, "beats": […],
                "chords": […], "words": […], "lines": […], "sections": […], "models": {…} } }
```
- `proposal` té la forma d'`ImportResult` (`src/lib/importers/types.ts`): el canconer en crea una
  proposta amb l'usuari sistema "Transcriptor", com fa el bulk import.
- `analysis` és el `SongAnalysis` complet (`src/transcriptor/schema.py`) per a `song_analyses`.
  Mida típica: 50-150 KB.

## `POST /api/transcriber/jobs/{id}/fail`

```json
{ "error": "RuntimeError: …", "released": false }
```
- `released: true`: el worker s'ha aturat a mitja feina (l'usuari l'ha desactivat o Ctrl+C). La feina
  ha de tornar a la cua **sense** comptar com a intent fallit.
- `released: false`: error real; el canconer incrementa `attempts` i decideix si la reintenta.

## Decisions obertes per a la Fase 6

1. On corre el worker per defecte (servidor, PC o els dos).
2. Límit d'intents i política de reintents (p. ex. 3 intents; els errors de YouTube no es reintenten
   fins al cap d'unes hores).
3. Si l'API ha d'enviar també l'àudio (per a cançons pujades com a fitxer) o només URL.
4. Versió mínima: com es publica (fitxer estàtic o camp a la BD).
