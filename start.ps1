# Starts Remastr locally: rebuilds the frontend when sources changed, then runs the backend (http://127.0.0.1:8765).
# Usage: powershell -ExecutionPolicy Bypass -File start.ps1 [-Rebuild]
param([switch]$Rebuild)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$frontend = Join-Path $root 'frontend'
$backend = Join-Path $root 'backend'

# Pick up tools installed after this shell started (winget updates the registry PATH only).
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
# Node comes from fnm, which only puts npm on PATH once its env is loaded.
if (-not (Get-Command npm -ErrorAction SilentlyContinue) -and (Get-Command fnm -ErrorAction SilentlyContinue)) {
    fnm env --shell powershell | Out-String | Invoke-Expression
    fnm use default --silent-if-unchanged | Out-Null
}
foreach ($tool in 'uv', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Warning "$tool nicht gefunden - bitte installieren bzw. in den PATH aufnehmen."
        exit 1
    }
}

if (-not (Test-Path (Join-Path $backend '.env'))) {
    Write-Warning 'backend/.env fehlt - kopiere backend/.env.example und trage die Werte ein.'
    exit 1
}

function Get-NewestWrite([string[]]$paths) {
    Get-ChildItem $paths -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object LastWriteTimeUtc -Maximum | ForEach-Object Maximum
}

Push-Location $frontend
try {
    $modules = Join-Path $frontend 'node_modules'
    if (-not (Test-Path $modules) -or (Get-Item 'package-lock.json').LastWriteTimeUtc -gt (Get-Item $modules).LastWriteTimeUtc) {
        Write-Host '>> npm install' -ForegroundColor Cyan
        npm install
        if ($LASTEXITCODE) { throw 'npm install fehlgeschlagen' }
    }

    $dist = Join-Path $frontend 'dist'
    $sources = 'src', 'public', 'index.html', 'package.json', 'vite.config.ts', 'tsconfig.app.json' |
        ForEach-Object { Join-Path $frontend $_ }
    if ($Rebuild -or -not (Test-Path $dist) -or (Get-NewestWrite $sources) -gt (Get-NewestWrite $dist)) {
        Write-Host '>> npm run build' -ForegroundColor Cyan
        npm run build
        if ($LASTEXITCODE) { throw 'Frontend-Build fehlgeschlagen' }
    }
} finally {
    Pop-Location
}

Push-Location $backend
try {
    Write-Host '>> uv run remastr' -ForegroundColor Cyan
    uv run remastr
} finally {
    Pop-Location
}
