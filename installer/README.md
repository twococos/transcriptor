# Instal·lador de Windows (Fase 7)

Instal·lador petit (uns 30 MB: `uv.exe` + el codi) per a col·laboradors. No cal tenir Python ni
permisos d'administrador. En instal·lar:

1. Copia `uv.exe`, el codi (`src/`), `pyproject.toml` i `uv.lock` a `%LOCALAPPDATA%\Programs\Transcriptor`.
2. Executa `bootstrap.ps1`, que:
   - mira si hi ha una GPU NVIDIA **útil** (`nvidia-smi`: compute capability ≥ 6.0 i ≥ 4 GB). Si el driver
     és massa antic per saber-ho (com la GTX 750 Ti del PC de proves), tria CPU;
   - fa `uv sync --frozen --extra cpu|cuda --extra app`. Baixa Python 3.11 i les dependències:
     ~1,3 GB en CPU, ~3,5 GB en CUDA. Si CUDA falla, torna a provar amb CPU.
3. Crea l'accés al menú Inici (i, si es marca, a l'arrencada de Windows) que obre
   `pythonw -m transcriptor.app`.

Els models (~2 GB) es baixen el primer cop que s'activa el worker, i l'app en mostra el progrés.
Les dades (models, cache) van a `%LOCALAPPDATA%\Transcriptor\dades`; la configuració i el registre
a `%APPDATA%\Transcriptor`. El token es desa xifrat amb DPAPI (només el pot llegir aquell usuari de Windows).

## Construir-lo

1. Instal·lar [Inno Setup 6](https://jrsoftware.org/isinfo.php) (amb l'idioma català).
2. Copiar `uv.exe` (de `%USERPROFILE%\.local\bin\uv.exe` o de les releases d'uv) a aquest directori.
3. `iscc installer\transcriptor.iss` → `installer\dist\Transcriptor-<versió>-instal-lador.exe`.

## Provat

- `bootstrap.ps1` en un directori temporal net d'aquest PC: tria CPU, instal·la en 1 min (amb la
  cache d'uv plena) i `import transcriptor.app` funciona. **No** s'ha compilat l'instal·lador
  (Inno Setup no és instal·lat) ni s'ha provat en un Windows net sense Python.
- L'app contra un servidor simulat (`proves/prova_app.py`): demana feina, la processa i envia el
  resultat. La finestra no s'ha pogut veure perquè la sessió estava bloquejada.

## Pendent

- Signatura de codi: sense certificat, SmartScreen mostra l'avís "Executa igualment". A més, Smart App
  Control pot bloquejar DLL sense signar de tercers (ctranslate2) la primera vegada: vegeu docs/proves.md.
- Autoactualització quan l'API respongui 426: cal decidir d'on es baixa la versió nova (Fase 6).
- Validació CUDA en una GPU llogada.
