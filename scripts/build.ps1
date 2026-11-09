param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildPath = Join-Path $ProjectRoot 'build'
$DistPath = Join-Path $ProjectRoot 'dist'
if ($Clean) {
    Remove-Item -LiteralPath $BuildPath, $DistPath -Recurse -Force -ErrorAction SilentlyContinue
}
Push-Location $ProjectRoot
try {
    python -m pip install -e ".[build]"
    pyinstaller --noconfirm --windowed --name TradeAgent --paths src src/trade_agent/__main__.py
}
finally {
    Pop-Location
}
