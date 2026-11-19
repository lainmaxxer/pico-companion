# Build a single-file Windows exe with PyInstaller (pip install pyinstaller first).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m PyInstaller --noconfirm --clean --onefile --windowed --name PicoCompanion pico_companion.py
Write-Host "Built: $PSScriptRoot\dist\PicoCompanion.exe"
