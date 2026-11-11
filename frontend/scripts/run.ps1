# 在 frontend 目录创建虚拟环境并启动 WordFlow。
$ErrorActionPreference = "Stop"
$Frontend = Split-Path -Parent $PSScriptRoot
$Repo = Split-Path -Parent $Frontend
Set-Location $Frontend

$Python = Join-Path $Frontend ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Join-Path $Repo ".venv\Scripts\python.exe"
}
if (-not (Test-Path $Python)) {
    py -3 -m venv (Join-Path $Frontend ".venv")
    $Python = Join-Path $Frontend ".venv\Scripts\python.exe"
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $Frontend "requirements.txt")
}

& $Python -m wordflow
