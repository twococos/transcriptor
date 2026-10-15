<#
  Construeix l'instal·lador MSI (installer\dist\Transcriptor-<versió>.msi).

  - Copia a installer\build\stage només els fitxers versionats (git ls-files): res de __pycache__,
    proves ni dades locals.
  - Hi afegeix uv.exe (el del PATH, o el que es passi amb -Uv).
  - Compila amb WiX 6 (dotnet tool install --global wix --version 6.0.2, i l'extensió
    WixToolset.Util.wixext/6.0.2).

  Ús: powershell -ExecutionPolicy Bypass -File installer\construeix.ps1 [-Uv C:\...\uv.exe]
  El mateix script el fa servir el workflow de GitHub Actions (.github/workflows/instal-lador.yml).
#>
param([string]$Uv = "")
$ErrorActionPreference = "Stop"
$arrel = Split-Path -Parent $PSScriptRoot
Set-Location $arrel

# Versió: la de pyproject.toml, que ha de coincidir amb la del paquet
$versio = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$versioPaquet = (Select-String -Path src\transcriptor\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
if ($versio -ne $versioPaquet) { throw "Versions diferents: pyproject.toml $versio, __init__.py $versioPaquet" }
if (-not (Test-Path LICENSE)) { throw "Falta el fitxer LICENSE" }

$stage = Join-Path $arrel "installer\build\stage"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null

$fitxers = git ls-files --cached --others --exclude-standard -- src pyproject.toml uv.lock README.md LICENSE
foreach ($f in $fitxers) {
    $desti = Join-Path $stage $f
    New-Item -ItemType Directory -Force (Split-Path -Parent $desti) | Out-Null
    Copy-Item $f $desti
}
Copy-Item installer\bootstrap.ps1, installer\transcriptor.ico $stage

# Python oficial dins el MSI (signat per la PSF): paquet NuGet + tcl/tk (tkinter, per a la finestra
# de l'app), que el NuGet no porta. Durant la instal·lació no es pot cridar msiexec (error 1618), per
# això el tcl/tk es desempaqueta aquí.
$cache = Join-Path $arrel "installer\build\cache"
New-Item -ItemType Directory -Force $cache | Out-Null
$ProgressPreference = "SilentlyContinue"
function Baixa($url, $desti, $hash) {
    if (-not (Test-Path $desti) -or (Get-FileHash $desti).Hash -ne $hash) {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $desti
    }
    if ((Get-FileHash $desti).Hash -ne $hash) { throw "Hash inesperat: $url" }
}
Baixa "https://www.nuget.org/api/v2/package/python/3.11.9" (Join-Path $cache "python.zip") `
    "9283876D58C017E0E846F95B490DA3BCA0FC0A6EE1134B2870677CFB7EEC3C67"
Baixa "https://www.python.org/ftp/python/3.11.9/amd64/tcltk.msi" (Join-Path $cache "tcltk.msi") `
    "C8845743FB77ABEC0F01FAA823BF3300E2113EF344758FC36360FEE3DD71A8A8"
$tmp = Join-Path $cache "python-zip"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path (Join-Path $cache "python.zip") -DestinationPath $tmp
Move-Item (Join-Path $tmp "tools") (Join-Path $stage "python")
Remove-Item -Recurse -Force $tmp
$tmp = Join-Path $cache "tcltk"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
$p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList "/a `"$(Join-Path $cache 'tcltk.msi')`" /qn TARGETDIR=`"$tmp`""
if ($p.ExitCode -ne 0) { throw "msiexec /a tcltk.msi: $($p.ExitCode)" }
foreach ($c in "DLLs", "Lib", "tcl") { Copy-Item -Recurse -Force (Join-Path $tmp $c) (Join-Path $stage "python") }
Remove-Item -Recurse -Force $tmp
Get-ChildItem (Join-Path $stage "python") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item -Force (Join-Path $stage "python\tcltk.msi") -ErrorAction SilentlyContinue

if (-not $Uv) { $Uv = (Get-Command uv).Source }
if ((Get-AuthenticodeSignature $Uv).Status -ne "Valid") { throw "uv.exe no està signat: $Uv" }
Copy-Item $Uv (Join-Path $stage "uv.exe")

$sortida = Join-Path $arrel "installer\dist\Transcriptor-$versio.msi"
wix build installer\transcriptor.wxs -ext WixToolset.Util.wixext -arch x64 `
    -d "Versio=$versio" -d "Stage=$stage" -o $sortida
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Instal·lador: $sortida"
