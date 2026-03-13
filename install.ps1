#Requires -Version 5.1
<#
.SYNOPSIS
    Install Vesta on Windows.
.DESCRIPTION
    Downloads and installs the Vesta desktop app or CLI from GitHub Releases.
.PARAMETER CliOnly
    Install CLI only (no desktop app).
.PARAMETER Version
    Install a specific version (e.g., 0.1.91).
.EXAMPLE
    irm https://raw.githubusercontent.com/elyxlz/vesta/master/install.ps1 | iex
.EXAMPLE
    & ./install.ps1 -CliOnly
#>
param(
    [switch]$CliOnly,
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$Repo = 'elyxlz/vesta'

if (-not $Version) {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest"
    $Version = $release.tag_name -replace '^v', ''
}

Write-Host "Installing Vesta v$Version..."

$TmpDir = Join-Path $env:TEMP "vesta-install-$(Get-Random)"
New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null

try {
    if ($CliOnly) {
        $Artifact = "vesta-x86_64-pc-windows-msvc.zip"
        $Url = "https://github.com/$Repo/releases/download/v$Version/$Artifact"
        $ZipPath = Join-Path $TmpDir $Artifact

        Write-Host "Downloading CLI..."
        Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

        Expand-Archive -Path $ZipPath -DestinationPath $TmpDir -Force

        $BinDir = Join-Path $env:LOCALAPPDATA 'vesta\bin'
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null

        Copy-Item (Join-Path $TmpDir 'vesta.exe') (Join-Path $BinDir 'vesta.exe') -Force
        Write-Host "Installed vesta to $BinDir\vesta.exe"

        # Add to PATH if not already there
        $UserPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
        if ($UserPath -notlike "*$BinDir*") {
            [Environment]::SetEnvironmentVariable('PATH', "$BinDir;$UserPath", 'User')
            $env:PATH = "$BinDir;$env:PATH"
            Write-Host "Added $BinDir to your PATH."
        }
    }
    else {
        $Installer = "Vesta_${Version}_x64-setup.exe"
        $Url = "https://github.com/$Repo/releases/download/v$Version/$Installer"
        $ExePath = Join-Path $TmpDir $Installer

        Write-Host "Downloading desktop app..."
        Invoke-WebRequest -Uri $Url -OutFile $ExePath -UseBasicParsing

        Write-Host "Running installer..."
        Start-Process -FilePath $ExePath -Wait
    }

    Write-Host "Done! Run 'vesta --help' to get started."
}
finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}
