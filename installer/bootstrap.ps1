<#
  Prepara l'entorn del Transcriptor dins el directori d'instal·lació (l'executa l'instal·lador).

  - Detecta si hi ha una GPU NVIDIA i tria PyTorch CUDA (cu126) o CPU.
  - Fa servir l'uv.exe que porta l'instal·lador: baixa Python 3.11 i totes les dependències
    (0,5-2,5 GB segons CPU/GPU). No cal tenir Python instal·lat ni compilar res.
  - Els models (~2 GB) es baixen el primer cop que s'activa el worker, amb progrés a l'app.

  Ús: powershell -ExecutionPolicy Bypass -File bootstrap.ps1 -Dir "C:\...\Transcriptor" [-Dispositiu auto|cpu|cuda]
#>
param(
    [Parameter(Mandatory = $true)][string]$Dir,
    [ValidateSet("auto", "cpu", "cuda")][string]$Dispositiu = "auto"
)
$ErrorActionPreference = "Stop"
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

# Tot dins el directori d'instal·lació: Python gestionat per uv i l'entorn virtual
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Dir "python"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Dir ".venv"
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:UV_LINK_MODE = "copy"

$uv = Join-Path $Dir "uv.exe"
& $uv sync --frozen --no-dev --no-editable --extra $Dispositiu --extra app
if ($LASTEXITCODE -ne 0 -and $Dispositiu -eq "cuda") {
    Write-Host "La instal·lació CUDA ha fallat; es torna a provar amb CPU"
    & $uv sync --frozen --no-dev --no-editable --extra cpu --extra app
}
if ($LASTEXITCODE -ne 0) { Stop-Transcript | Out-Null; exit $LASTEXITCODE }

# Comprovació ràpida
& (Join-Path $Dir ".venv\Scripts\python.exe") -c "import transcriptor, torch; print('Transcriptor', transcriptor.__version__, '- torch', torch.__version__, '- CUDA', torch.cuda.is_available())"
Stop-Transcript | Out-Null
exit $LASTEXITCODE
