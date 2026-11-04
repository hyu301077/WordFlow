# 安装打包依赖并生成 dist\WordFlow\WordFlow.exe。
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    py -3 -m venv (Join-Path $Root ".venv")
}
& $Python -m pip install -r (Join-Path $Root "requirements-dev.txt")

$Dictionary = Join-Path $Root "data\ecdict.db"
if (-not (Test-Path $Dictionary)) {
    Write-Warning "未找到 data\ecdict.db。可先运行 scripts\fetch_dict.ps1。没有词典时程序仍可运行，释义会显示为待补充。"
} else {
    Write-Host "将打包本地词典，输出目录大约 1GB。"
}

& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\wordflow.spec")
Write-Host "可执行文件：$(Join-Path $Root 'dist\WordFlow\WordFlow.exe')"
