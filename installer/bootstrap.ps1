<#
  Prepara l'entorn del Transcriptor dins el directori d'instal·lació (l'executa l'instal·lador).

  - Detecta si hi ha una GPU NVIDIA i tria PyTorch CUDA (cu126) o CPU.
  - Fa servir el Python oficial de `python\` (signat, perquè Smart App Control el deixi executar). El
    MSI ja l'inclou; si s'executa sol i no hi és, el baixa. Amb l'uv.exe que porta l'instal·lador,
    instal·la totes les dependències (0,5-2,5 GB segons CPU/GPU). No cal compilar res.
  - Els models (~2 GB) es baixen el primer cop que s'activa el worker, amb progrés a l'app.

  Ús: powershell -ExecutionPolicy Bypass -File bootstrap.ps1 -Dir "C:\...\Transcriptor" [-Dispositiu auto|cpu|cuda]
#>
param(
    [Parameter(Mandatory = $true)][string]$Dir,
    [ValidateSet("auto", "cpu", "cuda")][string]$Dispositiu = "auto"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # sense la barra, Invoke-WebRequest és molt més ràpid
$UrlPython = "https://www.nuget.org/api/v2/package/python/3.11.9"
$HashPython = "9283876D58C017E0E846F95B490DA3BCA0FC0A6EE1134B2870677CFB7EEC3C67"
# El paquet NuGet no porta tkinter (la finestra de l'app): l'afegim del tcltk.msi de la mateixa versió
$UrlTclTk = "https://www.python.org/ftp/python/3.11.9/amd64/tcltk.msi"
$HashTclTk = "C8845743FB77ABEC0F01FAA823BF3300E2113EF344758FC36360FEE3DD71A8A8"
Set-Location $Dir
$log = Join-Path $Dir "instal-lacio.log"
Start-Transcript -Path $log -Append | Out-Null

function Te-GpuUtil {
    # Una GPU NVIDIA només val la pena (2,5 GB de PyTorch CUDA) si és prou moderna i té prou memòria.
    # Si nvidia-smi no existeix o el driver no coneix "compute_cap", el driver és massa antic per a
    # CUDA 12.6 (p. ex. GTX 750 Ti amb driver vell): CPU.
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) { return $false }
    $sortida = & nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader,nounits 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $sortida) { return $false }
    foreach ($linia in @($sortida)) {
        $camps = $linia -split ",\s*"
        $memoria = [double]$camps[1]
        $cc = [double]::Parse($camps[2], [Globalization.CultureInfo]::InvariantCulture)
        Write-Host "GPU: $($camps[0]) - $memoria MiB - compute capability $cc"
        if ($cc -ge 6.0 -and $memoria -ge 4000) { return $true }
    }
    return $false
}

if ($Dispositiu -eq "auto") {
    if (Te-GpuUtil) { $Dispositiu = "cuda" } else { $Dispositiu = "cpu" }
}
Write-Host "Dispositiu triat: $Dispositiu"

# Python oficial (paquet NuGet de python.org): els executables estan signats per la Python Software
# Foundation. El Python que baixa uv (python-build-standalone) no ho està i Smart App Control el bloqueja.
$python = Join-Path $Dir "python\python.exe"
if (-not (Test-Path $python)) {
    $zip = Join-Path $env:TEMP "python-3.11.9-nuget.zip"
    Write-Host "Baixant Python 3.11.9 (python.org)..."
    Invoke-WebRequest -UseBasicParsing -Uri $UrlPython -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $HashPython) { throw "El paquet de Python no té el hash esperat" }
    $tmp = Join-Path $env:TEMP "python-3.11.9-nuget"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp
    Move-Item (Join-Path $tmp "tools") (Join-Path $Dir "python")
    Remove-Item -Recurse -Force $tmp, $zip
}
if (-not (Test-Path (Join-Path $Dir "python\DLLs\_tkinter.pyd"))) {
    $msi = Join-Path $env:TEMP "python-3.11.9-tcltk.msi"
    Write-Host "Baixant tcl/tk (python.org)..."
    Invoke-WebRequest -UseBasicParsing -Uri $UrlTclTk -OutFile $msi
    if ((Get-FileHash $msi -Algorithm SHA256).Hash -ne $HashTclTk) { throw "El paquet tcl/tk no té el hash esperat" }
    # Instal·lació administrativa: només desempaqueta (DLLs, Lib\tkinter, tcl), no registra res
    $tmp = Join-Path $env:TEMP "python-3.11.9-tcltk"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$tmp`""
    if ($p.ExitCode -ne 0) { throw "No s'ha pogut desempaquetar tcl/tk (msiexec $($p.ExitCode))" }
    foreach ($c in "DLLs", "Lib", "tcl") { Copy-Item -Recurse -Force (Join-Path $tmp $c) (Join-Path $Dir "python") }
    Remove-Item -Recurse -Force $tmp, $msi
}

# Tot dins el directori d'instal·lació
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Dir ".venv"
$env:UV_LINK_MODE = "copy"

$uv = Join-Path $Dir "uv.exe"
& $uv sync --frozen --no-dev --no-editable --python $python --extra $Dispositiu --extra app
if ($LASTEXITCODE -ne 0 -and $Dispositiu -eq "cuda") {
    Write-Host "La instal·lació CUDA ha fallat; es torna a provar amb CPU"
    & $uv sync --frozen --no-dev --no-editable --python $python --extra cpu --extra app
}
if ($LASTEXITCODE -ne 0) { Stop-Transcript | Out-Null; exit $LASTEXITCODE }

# Comprovació ràpida
& (Join-Path $Dir ".venv\Scripts\python.exe") -c "import transcriptor, tkinter, torch; print('Transcriptor', transcriptor.__version__, '- torch', torch.__version__, '- CUDA', torch.cuda.is_available())"
Stop-Transcript | Out-Null
exit $LASTEXITCODE
