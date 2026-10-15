# Instal·lador de Windows (Fase 7)

Instal·lador MSI (~31 MB) per a col·laboradors. No cal tenir Python ni permisos d'administrador.
En instal·lar:

1. Copia a `%LOCALAPPDATA%\Programs\Transcriptor`: el codi (`src/`), `pyproject.toml`, `uv.lock`,
   `uv.exe` i un **Python 3.11 oficial** (paquet NuGet de python.org + tcl/tk per a tkinter).
2. Executa `bootstrap.ps1` (amb el PowerShell del sistema, sense finestra), que:
   - mira si hi ha una GPU NVIDIA **útil** (`nvidia-smi`: compute capability ≥ 6.0 i ≥ 4 GB). Si el driver
     és massa antic per saber-ho (com la GTX 750 Ti del PC de proves), tria CPU;
   - fa `uv sync --frozen --extra cpu|cuda --extra app` sobre aquell Python: ~1,3 GB en CPU, ~3,5 GB
     en CUDA. Si CUDA falla, torna a provar amb CPU. Registre a `instal-lacio.log`.
3. Crea l'accés al menú Inici que obre `pythonw -m transcriptor.app`. L'arrencada amb Windows
   s'activa des de l'app.

Forçar el dispositiu: `msiexec /i Transcriptor-<versió>.msi DISPOSITIU=cpu`.
En desinstal·lar s'esborren també el `.venv` i el Python (en actualitzar, no).

Els models (~1,8 GB en CPU) es baixen el primer cop que s'activa el worker. L'app en mostra el progrés
amb els bytes rebuts, la velocitat i el temps que falta (a ~1,2 MB/s, uns 25 min). Un compte de Hugging
Face no ho accelera: el límit és la connexió (el model de Beat This!, que no és a Hugging Face, baixa a
la mateixa velocitat); el token només amplia el nombre de peticions permeses.

Les dades (models, cache) van a `%LOCALAPPDATA%\Transcriptor\dades`; la configuració i el registre
a `%APPDATA%\Transcriptor`. El token es desa xifrat amb DPAPI (només el pot llegir aquell usuari de Windows).
Les cançons fetes es desen a `dadesetes\<id>` (anàlisi i, si l'usuari ho vol, l'àudio en Opus,
~3 MB) per obrir-les al visor des de l'app; es poden esborrar d'una en una o totes alhora.

L'app s'executa amb `pythonw` (sense consola, `sys.stdout` és `None`): `main()` redirigeix stdout i
stderr a `os.devnull`, perquè torch.hub i tqdm hi escriuen el progrés de les descàrregues.

## Per què MSI i Python oficial: Smart App Control

Smart App Control (SAC, actiu per defecte en instal·lacions noves de Windows 11) bloqueja els
executables i DLL sense signar que no té per coneguts, i no ofereix "Executa igualment".

- **Python**: el de python-build-standalone (el que baixa uv) no està signat. El 2026-10-15 SAC el va
  començar a bloquejar en aquest PC, tot i que la nit abans funcionava (decideix per reputació al
  núvol). El Python de python.org està signat per la Python Software Foundation.
- **Inno Setup**: el primer instal·lador era d'Inno Setup, però en executar-se extreu el seu motor
  (`Setup.e32`, sense signar) com a `.tmp`, i SAC el bloqueja. Signar l'`.exe` exterior no ho
  arregla, perquè l'Inno no passa `Setup.e32` pel SignTool; altres instal·ladors Inno signats tenen el
  mateix problema.
- **MSI**: l'executa `msiexec` (de Microsoft) i no porta cap executable propi. Tots els binaris de
  dins ja vénen signats: `uv.exe` (OpenAI), Python (PSF) i la DLL de `WixQuietExec` (FireGiant). Només
  cal signar el `.msi` (SignPath, vegeu més avall).

## Construir-lo

Requisits: .NET SDK 8 i WiX 6 (`dotnet tool install --global wix --version 6.0.2` i
`wix extension add -g WixToolset.Util.wixext/6.0.2`), `uv` al PATH i un fitxer `LICENSE` a l'arrel.

```powershell
powershell -ExecutionPolicy Bypass -File installer\construeix.ps1
# → installer\dist\Transcriptor-<versió>.msi
```

`construeix.ps1` copia només els fitxers versionats (`git ls-files`) a `installer\build\stage`, hi
afegeix uv i el Python (baixats amb el hash fixat, en cache a `installer\build\cache`) i crida `wix`.
El workflow [instal-lador.yml](../.github/workflows/instal-lador.yml) fa el mateix a GitHub Actions i
envia el MSI a signar a SignPath.

## Signatura amb SignPath

- Projecte `transcriptor`, configuració d'artefacte `msi` ([signpath-msi.xml](signpath-msi.xml)),
  polítiques `test-signing` (execució manual del workflow) i `release-signing` (etiquetes `vX.Y.Z`,
  amb aprovació manual).
- Al repo: secret `SIGNPATH_API_TOKEN` i variable `SIGNPATH_ORGANIZATION_ID`.

## Provat (2026-10-15, en aquest PC amb SAC actiu)

- MSI sense signar: `msiexec /i` per usuari en 66 s (cache d'uv plena), `tkinter`, `torch` i
  `transcriptor.app` funcionen, l'app arrenca i **cap bloqueig de SAC** dins la instal·lació.
  `msiexec /x` ho deixa tot net (carpeta, accés al menú, registre).
- Passada completa del pipeline (Demucs, Beat This!, BTC, Whisper) amb el Python oficial sense cap bloqueig.
- Worker real contra el canconer en mode producció (`next start`, branca `transcripcio`, còpia de la
  BD): una feina `new` i una `analyze`, totes dues `done`.
- **No provat**: la finestra de l'app (sessió bloquejada), un Windows net, el MSI ja signat, CUDA.

## Pendent

- Autoactualització quan l'API respongui 426: ara l'app només avisa que cal actualitzar.
- Validació CUDA en una GPU llogada.
- SAC pot bloquejar DLL sense signar de dependències (ctranslate2) la primera vegada: vegeu
  docs/proves.md. Amb el MSI no s'ha reproduït.
