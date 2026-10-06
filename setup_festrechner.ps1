<#
.SYNOPSIS
    One-time setup for the DM Timesheet autostart updater on the desktop PC
    ("Festrechner"). Run this once, interactively, in a normal PowerShell
    window — after this, the app updates and runs itself silently on every
    login with no terminal ever appearing.

.DESCRIPTION
    1. Clones (or updates) the git repo into -InstallDir.
    2. Creates a virtual environment and installs requirements.txt.
    3. Builds DM_Timesheet_Updater.exe (windowed, no console) with PyInstaller.
    4. Creates a shortcut to that .exe in the Windows Startup folder, so it
       runs automatically on every login.

    After this script finishes, copy these three files into
    "<InstallDir>\programm\" (they contain secrets and are never stored in
    git, so they must be copied manually, once, from the laptop):
        .env
        (and into "<InstallDir>\kalender_reader\":)
        credentials.json
        token.pickle   (created automatically on first calendar login if
                        missing — a browser window will open once)

.PARAMETER RepoUrl
    Git remote to clone from. Defaults to the project's GitHub repo.

.PARAMETER InstallDir
    Where the repo lives on this PC. Defaults to a DM_Timesheet folder next
    to this script's own location, or under the current user's profile.

.EXAMPLE
    .\setup_festrechner.ps1
    .\setup_festrechner.ps1 -InstallDir "C:\Tools\DM_Timesheet"
#>

param(
    [string]$RepoUrl = "git@github-public:H-Held/DM_Timesheet.git",
    [string]$InstallDir = "$env:USERPROFILE\DM_Timesheet"
)

$ErrorActionPreference = "Stop"

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "'$name' was not found on PATH. $hint"
    }
}

Write-Host "=== DM Timesheet — Festrechner setup ===" -ForegroundColor Cyan

Require-Command "git" "Install Git for Windows first: https://git-scm.com/download/win"
Require-Command "python" "Install Python 3.11+ first: https://www.python.org/downloads/"

# 1. Clone or update the repo -------------------------------------------------
if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Host "Repo already present at $InstallDir — pulling latest ..." -ForegroundColor Yellow
    git -C $InstallDir pull --ff-only
} else {
    Write-Host "Cloning $RepoUrl into $InstallDir ..." -ForegroundColor Yellow
    git clone $RepoUrl $InstallDir
}

# 2. Virtual environment + dependencies --------------------------------------
$venvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment ..." -ForegroundColor Yellow
    python -m venv (Join-Path $InstallDir ".venv")
}

Write-Host "Installing dependencies ..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $InstallDir "requirements.txt") --quiet

# 3. Build the autostart updater .exe -----------------------------------------
Write-Host "Building DM_Timesheet_Updater.exe ..." -ForegroundColor Yellow
Push-Location $InstallDir
& $venvPython -m PyInstaller DM_Timesheet_Updater.spec --noconfirm | Out-Null
Pop-Location

$updaterExe = Join-Path $InstallDir "dist\DM_Timesheet_Updater.exe"
if (-not (Test-Path $updaterExe)) {
    throw "Build failed — $updaterExe was not created. Check the PyInstaller output above."
}

# 4. Put the updater exe where the shortcut will point, and shortcut it ------
# Keep the .exe inside the repo (next to the "updater" sources) so it can
# find the repo root as its own parent folder at runtime.
$updaterHome = Join-Path $InstallDir "updater_bin"
New-Item -ItemType Directory -Force -Path $updaterHome | Out-Null
Copy-Item $updaterExe -Destination $updaterHome -Force

$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "DM_Timesheet_Updater.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $updaterHome "DM_Timesheet_Updater.exe"
$shortcut.WorkingDirectory = $updaterHome
$shortcut.Description = "DM Timesheet — checks for updates and runs silently"
$shortcut.Save()

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "Autostart shortcut created: $shortcutPath"
Write-Host ""
Write-Host "Before it can actually run, copy these files from the laptop (never in git):" -ForegroundColor Yellow
Write-Host "  $InstallDir\programm\.env"
Write-Host "  $InstallDir\kalender_reader\credentials.json"
Write-Host "  $InstallDir\kalender_reader\token.pickle   (or let it open a one-time login)"
Write-Host ""
Write-Host "You can test it right now without rebooting:"
Write-Host "  & `"$updaterHome\DM_Timesheet_Updater.exe`""
Write-Host "Then check '$updaterHome\updater.log' and '$InstallDir\programm\dm_downloader.log'."
