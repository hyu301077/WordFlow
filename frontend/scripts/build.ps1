# 安装打包依赖并生成 frontend\dist\WordFlow\WordFlow.exe。
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
}
& $Python -m pip install -r (Join-Path $Frontend "requirements-dev.txt")

$Dictionary = Join-Path $Frontend "data\ecdict.db"
if (-not (Test-Path $Dictionary)) {
    Write-Warning "未找到 data\ecdict.db。可先运行 scripts\fetch_dict.ps1。没有词典时程序仍可运行，释义会显示为待补充。"
} else {
    Write-Host "将打包本地词典，输出目录大约 1GB。"
}

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Frontend "packaging\wordflow.spec")
Write-Host "可执行文件：$(Join-Path $Frontend 'dist\WordFlow\WordFlow.exe')"
