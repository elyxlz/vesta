$ErrorActionPreference = "Stop"

$Repo = "elyxlz/vesta"
$Version = ""
$InstallCli = $false
$InstallApp = $false

foreach ($arg in $args) {
    if ($arg -match "^--version=(.+)$") {
        $Version = $Matches[1]
    }
    elseif ($arg -eq "--cli") { $InstallCli = $true }
    elseif ($arg -eq "--app") { $InstallApp = $true }
    elseif ($arg -eq "--server") {
        Write-Host "Error: --server is only available on Linux (use WSL2)"
        exit 1
    }
    elseif ($arg -eq "--help" -or $arg -eq "-h") {
        Write-Host "Usage: irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex"
        Write-Host ""
        Write-Host "Installs vesta CLI and desktop app on Windows."
        Write-Host "By default, both are installed."
        Write-Host ""
        Write-Host "Options:"
        Write-Host "  --cli              Install only the CLI"
        Write-Host "  --app              Install only the desktop app"
        Write-Host "  --version=X.Y.Z   Install a specific version"
        Write-Host "  --help             Show this help"
        exit 0
    }
}

# If no component flags given, install everything
if (-not $InstallCli -and -not $InstallApp) {
    $InstallCli = $true
    $InstallApp = $true
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
    if ($InstallCli) {
        # --- CLI ---
        $CliArtifact = "vesta-x86_64-pc-windows-msvc.zip"
        $CliZip = Join-Path $TmpDir "vesta.zip"
        $CliUrl = "https://github.com/$Repo/releases/download/v$Version/$CliArtifact"

        Write-Host "Downloading vesta CLI..."
        Invoke-WebRequest -Uri $CliUrl -OutFile $CliZip -UseBasicParsing

        Expand-Archive -Path $CliZip -DestinationPath $TmpDir -Force

        $BinDir = Join-Path $env:LOCALAPPDATA "vesta\bin"
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
        Copy-Item (Join-Path (Join-Path $TmpDir "vesta-windows") "vesta.exe") -Destination (Join-Path $BinDir "vesta.exe") -Force

        # Add to PATH if not already there
        $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if ($UserPath -notlike "*$BinDir*") {
            [Environment]::SetEnvironmentVariable("Path", "$BinDir;$UserPath", "User")
            Write-Host "  Added $BinDir to PATH"
        }
        $env:Path = "$BinDir;$env:Path"

        Write-Host "  OK: vesta CLI -> $BinDir\vesta.exe"
    }

    if ($InstallApp) {
        # --- Desktop app ---
        $AppArtifact = "Vesta_${Version}_x64-setup.exe"
        $AppExe = Join-Path $TmpDir $AppArtifact
        $AppUrl = "https://github.com/$Repo/releases/download/v$Version/$AppArtifact"

        Write-Host "Downloading desktop app..."
        Invoke-WebRequest -Uri $AppUrl -OutFile $AppExe -UseBasicParsing

        Write-Host "Running installer..."
        Start-Process -FilePath $AppExe -ArgumentList "/S" -Wait
        Write-Host "  OK: Vesta desktop app"
    }

    Write-Host ""
    Write-Host "Done! Get started:"
    Write-Host "  vesta connect <host>#<key>   # Connect to a remote vestad"
    Write-Host "  Open Vesta app and connect to your server"
}
finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}
