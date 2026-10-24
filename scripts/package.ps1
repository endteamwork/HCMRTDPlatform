# Package each Lambda into dist/<name>.zip with Linux-compatible dependencies.
# Run from the repo root: powershell -File scripts\package.ps1

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $repo "dist"
New-Item -ItemType Directory -Force $dist | Out-Null

# lambda name -> extra pip packages (boto3 is provided by the Lambda runtime)
$lambdas = @{
    "jobs_ingest"          = @("requests")
    "fx_ingest"            = @("requests")
    "benchmarks_scraper"   = @("requests", "beautifulsoup4")
    "event_router"         = @()
    "benchmarks_processor" = @()
    "fx_processor"         = @("python-tds")
}

foreach ($name in $lambdas.Keys) {
    $build = Join-Path $dist "build_$name"
    if (Test-Path $build) { Remove-Item -Recurse -Force $build }
    New-Item -ItemType Directory -Force $build | Out-Null

    Copy-Item (Join-Path $repo "src\lambdas\$name\handler.py") $build
    Copy-Item -Recurse (Join-Path $repo "src\common") (Join-Path $build "common")

    $pkgs = $lambdas[$name]
    if ($pkgs.Count -gt 0) {
        pip install --quiet --target $build `
            --platform manylinux2014_x86_64 --python-version 3.11 `
            --only-binary=:all: --upgrade @pkgs
        if ($LASTEXITCODE -ne 0) { throw "pip install failed for $name" }
    }

    $zip = Join-Path $dist "$name.zip"
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Compress-Archive -Path (Join-Path $build "*") -DestinationPath $zip
    Write-Host "built $zip"
}
