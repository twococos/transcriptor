; Instal·lador del Transcriptor (Inno Setup 6).
; Construir: vegeu installer/README.md. Instal·lació per usuari, sense permisos d'administrador.

#define Versio "0.1.0"

[Setup]
AppId={{6B0C5E1F-6E7A-4B8E-9C37-7A1B2D9C4E51}
AppName=Transcriptor
AppVersion={#Versio}
AppPublisher=El Cançoner (guitarreo.cat)
AppPublisherURL=https://guitarreo.cat
DefaultDirName={localappdata}\Programs\Transcriptor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Transcriptor-{#Versio}-instal-lador
SetupIconFile=transcriptor.ico
UninstallDisplayIcon={app}\transcriptor.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "ca"; MessagesFile: "compiler:Languages\Catalan.isl"

[Tasks]
Name: "arrencada"; Description: "Arrenca el Transcriptor amb Windows"; Flags: unchecked
Name: "cpu"; Description: "Fes servir només la CPU encara que hi hagi una GPU NVIDIA"; Flags: unchecked

[Files]
Source: "uv.exe"; DestDir: "{app}"
Source: "bootstrap.ps1"; DestDir: "{app}"
Source: "transcriptor.ico"; DestDir: "{app}"
Source: "..\pyproject.toml"; DestDir: "{app}"
Source: "..\uv.lock"; DestDir: "{app}"
Source: "..\README.md"; DestDir: "{app}"
Source: "..\src\*"; DestDir: "{app}\src"; Flags: recursesubdirs; Excludes: "__pycache__,*.pyc"

[Icons]
Name: "{userprograms}\Transcriptor"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m transcriptor.app"; WorkingDir: "{app}"; IconFilename: "{app}\transcriptor.ico"
Name: "{userstartup}\Transcriptor"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m transcriptor.app"; WorkingDir: "{app}"; IconFilename: "{app}\transcriptor.ico"; Tasks: arrencada

[Run]
; Baixa Python i les dependències (pot trigar uns minuts)
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\bootstrap.ps1"" -Dir ""{app}"" -Dispositiu auto"; StatusMsg: "Instal·lant Python i les dependències (pot trigar uns minuts)..."; Flags: runhidden; Tasks: not cpu
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\bootstrap.ps1"" -Dir ""{app}"" -Dispositiu cpu"; StatusMsg: "Instal·lant Python i les dependències (pot trigar uns minuts)..."; Flags: runhidden; Tasks: cpu
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m transcriptor.app"; WorkingDir: "{app}"; Description: "Obre el Transcriptor"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
