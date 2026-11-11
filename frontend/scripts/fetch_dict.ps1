# 下载 ECDICT（MIT）并解压为 data\ecdict.db。约 200MB 压缩包，解压后约 800MB。
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Data = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $Data | Out-Null

$Target = Join-Path $Data "ecdict.db"
if (Test-Path $Target) {
    Write-Host "词典已存在：$Target"
    exit 0
}

$Zip = Join-Path $Data "ecdict-sqlite-28.zip"
$Url = "https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip"
if (-not (Test-Path $Zip)) {
    Write-Host "正在下载 $Url"
    curl.exe -L --fail -o $Zip $Url
}

Write-Host "正在解压"
tar -xf $Zip -C $Data
$Extracted = Join-Path $Data "stardict.db"
if (Test-Path $Extracted) {
    Move-Item -Force $Extracted $Target
}
if (-not (Test-Path $Target)) {
    throw "解压后没有找到 ecdict.db 或 stardict.db"
}
Write-Host "词典已保存到 $Target"
