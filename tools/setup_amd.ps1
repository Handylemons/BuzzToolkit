# EXPERIMENTAL: voice trainer on an AMD Radeon GPU under Windows, using AMD's ROCm build of PyTorch.
# AMD lists RX 9070/9060 XT, RX 7900 XTX and RX 7700 class cards (gfx1100/gfx1101/gfx1200/gfx1201); AMD does not
# officially support training on Windows, so this ends with a one-minute GPU training check.
# Needs: Python 3.12 (python.org installer, with the "py" launcher) and AMD Adrenalin driver 26.2.2 or newer.
# Run from the BuzzToolkit folder:  powershell -ExecutionPolicy Bypass -File tools\setup_amd.ps1
# Creates tools\clone_venv_amd (the NVIDIA/CPU tools\clone_venv is left untouched).
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $PSScriptRoot "clone_venv_amd"
$py = Join-Path $venv "Scripts\python.exe"
& py -3.12 -c "import sys; print('Python', sys.version.split()[0])"
if ($LASTEXITCODE) { throw "Python 3.12 not found. Install it from python.org (tick 'py launcher') and run this again." }
if (-not (Test-Path $py)) { & py -3.12 -m venv $venv }
& $py -m pip install --upgrade pip
# 1) everything except PyTorch, exactly as the NVIDIA build pins it (no dependency resolution: chatterbox pins torch 2.6)
$req = Join-Path $env:TEMP "buzz_clone_requirements_amd.txt"
Get-Content (Join-Path $PSScriptRoot "clone_requirements.txt") |
    Where-Object { $_ -notmatch '^(torch|torchaudio)==' -and $_ -notmatch '^--extra-index-url' } | Set-Content $req
& $py -m pip install --no-deps -r $req
if ($LASTEXITCODE) { throw "Installing the toolkit's Python packages failed (see above)." }
# 2) AMD's PyTorch last, so its own dependencies (and AMD's 'rocm' package) win
& $py -m pip install --no-cache-dir -f "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/" "torch==2.9.1+rocm7.2.1" "torchaudio==2.9.1+rocm7.2.1"
if ($LASTEXITCODE) { throw "Installing AMD's PyTorch failed (see above)." }
# 3) does training actually run on this card?
Push-Location $root
try { & $py -m voice_trainer.gpu_check } finally { Pop-Location }
if ($LASTEXITCODE) { Write-Host "GPU check FAILED - use tools\clone_venv (CPU) instead." -ForegroundColor Red; exit 1 }
Write-Host "Ready. Train with:  tools\clone_venv_amd\Scripts\python -m voice_trainer.run ... --preset standard" -ForegroundColor Green
