$ErrorActionPreference = "Stop"

$Repo = "elyxlz/vesta"
$Version = ""

foreach ($arg in $args) {
    if ($arg -match "^--version=(.+)$") {
        $Version = $Matches[1]
    }
    elseif ($arg -eq "--server") {
        Write-Host "Error: --server is only available on Linux (use WSL2)"
        exit 1
    }
    elseif ($arg -eq "--help" -or $arg -eq "-h") {
        Write-Host "Usage: irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex"
        Write-Host ""
        Write-Host "Installs the Vesta desktop app on Windows."
        Write-Host ""
        Write-Host "Options:"
        Write-Host "  --version=X.Y.Z   Install a specific version"
        Write-Host "  --help             Show this help"
        exit 0
    }
}

if (-not $Version) {
    $Release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
    $Version = $Release.tag_name -replace "^v", ""
}

Write-Host "Installing Vesta v$Version..."
Write-Host ""

$TmpDir = Join-Path $env:TEMP "vesta-install-$(Get-Random)"
New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null

try {
    # --- Desktop app ---
    $AppArtifact = "Vesta_${Version}_x64.exe"
    $AppExe = Join-Path $TmpDir $AppArtifact
    $AppUrl = "https://github.com/$Repo/releases/download/v$Version/$AppArtifact"

    Write-Host "Downloading desktop app..."
    Invoke-WebRequest -Uri $AppUrl -OutFile $AppExe -UseBasicParsing

    Write-Host "Running installer..."
    Start-Process -FilePath $AppExe -ArgumentList "/S" -Wait
    Write-Host "  OK: Vesta desktop app"

    Write-Host ""
    Write-Host "Done! Get started:"
    Write-Host "  Open the Vesta app and paste your gateway's connect link."
}
finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}
