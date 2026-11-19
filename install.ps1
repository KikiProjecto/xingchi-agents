# xingchi-codex installer for Windows.
# Points the Codex CLI at the Xingchi upstream (OpenAI Responses API).
# No local proxy, one key.
#
# NAME COLLISION WARNING: PowerShell variable names are case-INsensitive, so
# $Upstream and $upstream are the same variable. An earlier revision used that
# pair for the base URL and the API key; pasting the key silently overwrote the
# URL, which wrote base_url = "<api key>" into config.toml, pointed
# OPENAI_BASE_URL at the key, and made "verification" try to DNS-resolve the key
# as a hostname ("could not reach upstream /models"). Keep $BaseUrl and $ApiKey
# distinct, and never reintroduce the old pair. tests/test_install_windows.py
# enforces this.
#requires -version 5.1
param(
    [switch]$Yes,
    [switch]$NoPath,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'

# Windows PowerShell 5.1 negotiates SSL3/TLS1.0 by default on older builds, which
# fails against both codeload.github.com and the Xingchi API.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$Repo = if ($env:XINGCHI_REPO) { $env:XINGCHI_REPO } else { 'kikiprojecto/xingchi-codex' }
$Branch = if ($env:XINGCHI_BRANCH) { $env:XINGCHI_BRANCH } else { 'main' }
$XDir = if ($env:XINGCHI_HOME) { $env:XINGCHI_HOME } else { Join-Path $env:USERPROFILE '.xingchi' }
$Bin = if ($env:XINGCHI_BIN) { $env:XINGCHI_BIN } else { Join-Path $env:LOCALAPPDATA 'xingchi\bin' }
$BaseUrl = if ($env:XINGCHI_UPSTREAM) { $env:XINGCHI_UPSTREAM } else { 'https://api.xingchiapi.com/v1' }
# A trailing slash would otherwise produce "//models" in the catalog URL.
$BaseUrl = "$BaseUrl".Trim().TrimEnd('/')
$Model = 'gpt-6.1-sol'
$KeyFile = Join-Path $XDir 'upstream.key'
$SkipPath = $NoPath -or ($env:XINGCHI_NO_PATH -eq '1')

if ($Help) {
    Write-Host "usage: install.ps1 [-Yes] [-NoPath]`n"
    Write-Host "Configures Codex for Xingchi (default: $Model)."
    Write-Host "Stores your Xingchi API key in $KeyFile and writes"
    Write-Host 'config.toml and a four-model catalog under CODEX_HOME (default ~/.codex).'
    Write-Host "Connects directly to $BaseUrl. Choose model and reasoning with /model.`n"
    Write-Host "  -Yes     never prompt; requires XINGCHI_API_KEY"
    Write-Host "  -NoPath  do not add the launcher directory to your user PATH"
    return
}

$SelfDir = $PSScriptRoot
if (-not $SelfDir -or -not (Test-Path (Join-Path $SelfDir 'lib\config.py')) -or -not (Test-Path (Join-Path $SelfDir 'lib\models.json'))) {
    $tmp = Join-Path $env:TEMP ("xingchi-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'src.zip'
    Write-Host "download $Repo ($Branch)..."
    Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    $childArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $src.FullName 'install.ps1'))
    if ($Yes) { $childArgs += '-Yes' }
    if ($NoPath) { $childArgs += '-NoPath' }
    & powershell @childArgs
    if ($LASTEXITCODE -ne 0) { Write-Error "installer failed (exit $LASTEXITCODE)" }
    return
}

function Test-PythonExe($exe) {
    try {
        & $exe -c "import sys; print(sys.version_info[0])" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$python = $null
foreach ($candidate in @('python3', 'python', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd -and (Test-PythonExe $cmd.Source)) { $python = $cmd.Source; break }
}
if (-not $python) {
    Write-Host 'python3 missing, installing with winget...'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    }
    foreach ($candidate in @('python3', 'python', 'py')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd -and (Test-PythonExe $cmd.Source)) { $python = $cmd.Source; break }
    }
}
if (-not $python) {
    throw 'install Python 3 from https://www.python.org/downloads/ then re-run'
}

New-Item -ItemType Directory -Force -Path $XDir, $Bin | Out-Null

Write-Host "`n[1/3] Xingchi API key"
$ApiKey = $env:XINGCHI_API_KEY
if (-not $ApiKey -and (Test-Path $KeyFile)) {
    $ApiKey = (Get-Content $KeyFile -Raw).Trim()
}
if (-not $ApiKey) {
    if ($Yes) { throw 'set XINGCHI_API_KEY (your xingchiapi key) or run without -Yes' }
    Write-Host "`nCreate a key at https://xingchiapi.com/keys, copy it, then paste it here (input is hidden)."
    $secure = Read-Host 'Paste your xingchiapi API key' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::FreeBSTR($bstr)
    }
}
# Pasting from a browser can carry spaces or CR; trim or the key fails with 401.
$ApiKey = "$ApiKey".Trim()
if (-not $ApiKey) { throw 'empty API key' }
[IO.File]::WriteAllText($KeyFile, "$ApiKey`n")

Write-Host "`n[2/3] Codex CLI"
$CliCompatible = $false
if (Get-Command codex -ErrorAction SilentlyContinue) {
    try {
        $CliVersion = (& codex --version 2>$null | Out-String).Trim()
        if ($CliVersion) {
            & $python (Join-Path $SelfDir 'lib\config.py') check-cli $CliVersion
            $CliCompatible = ($LASTEXITCODE -eq 0)
        }
    } catch { $CliCompatible = $false }
}
if (-not $CliCompatible) {
    Write-Host '  installing/updating @openai/codex (0.170.0 or newer required)...'
    if (-not (Get-Command npm -ErrorAction SilentlyContinue) -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host '  installing Node.js...'
        winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements --silent
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'npm is missing. Install Node.js, then: npm install -g @openai/codex'
    }
    & npm install -g @openai/codex
    if ($LASTEXITCODE -ne 0) { throw 'npm install -g @openai/codex failed' }
    # This session still has the pre-install PATH, so codex.cmd (dropped in
    # %APPDATA%\npm) is not visible yet. Refresh before the launchers rely on it.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $npmBin = Join-Path $env:APPDATA 'npm'
    if (-not (Get-Command codex -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $npmBin 'codex.cmd'))) {
        $env:Path = "$npmBin;$env:Path"
    }
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw 'codex is not on PATH; add npm to PATH, then rerun the installer'
}
$CliVersion = (& codex --version 2>$null | Out-String).Trim()
& $python (Join-Path $SelfDir 'lib\config.py') check-cli $CliVersion
if ($LASTEXITCODE -ne 0) { throw 'Codex update did not install a compatible CLI' }

Write-Host "`n[3/3] Installing the model catalog, reasoning menus and launchers"
$env:XINGCHI_API_KEY = $ApiKey
$env:XINGCHI_UPSTREAM = $BaseUrl
$env:XINGCHI_HOME = $XDir
& $python (Join-Path $SelfDir 'lib\config.py') codex
if ($LASTEXITCODE -ne 0) { throw 'config for codex failed' }

# Single-quoted here-strings: nothing here is expanded by PowerShell, so a value
# can never be substituted into the wrong placeholder the way $Upstream/$upstream
# once was. Values are filled in below with a literal .Replace().
$xingchiCmd = @'
@echo off
setlocal
set "XINGCHI_KEY_FILE=__KEY_FILE__"
if not exist "%XINGCHI_KEY_FILE%" (
  echo error: API key missing at "%XINGCHI_KEY_FILE%" 1>&2
  exit /b 1
)
set "OPENAI_API_KEY="
set /p OPENAI_API_KEY=<"%XINGCHI_KEY_FILE%"
if not defined OPENAI_API_KEY (
  echo error: API key empty at "%XINGCHI_KEY_FILE%" 1>&2
  exit /b 1
)
set "OPENAI_BASE_URL=__BASE_URL__"
call codex --no-daemon %*
exit /b %ERRORLEVEL%
'@
$xingchiCmd = $xingchiCmd.Replace('__KEY_FILE__', $KeyFile).Replace('__BASE_URL__', $BaseUrl)
[IO.File]::WriteAllText((Join-Path $Bin 'xingchi-codex.cmd'), $xingchiCmd.TrimEnd() + "`r`n")

$statusCmd = @'
@echo off
echo API:   __BASE_URL__ (direct, OpenAI Responses)
echo models and reasoning: use /model in Codex
if exist "__KEY_FILE__" (echo key     set) else (echo key     missing)
where codex >NUL 2>&1
if errorlevel 1 (echo codex   missing) else (echo codex   installed)
echo.
echo start with: xingchi-codex
'@
# The status command shows that the key is present, never the key itself.
$statusCmd = $statusCmd.Replace('__BASE_URL__', $BaseUrl).Replace('__KEY_FILE__', $KeyFile)
[IO.File]::WriteAllText((Join-Path $Bin 'xingchi.cmd'), $statusCmd.TrimEnd() + "`r`n")

if ($SkipPath) {
    Write-Host "leaving user PATH untouched (-NoPath)"
} else {
    # Compare whole PATH entries; a substring test also matched "...\bin2".
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { $userPath = '' }
    $segments = @($userPath.Split(';') | Where-Object { $_ })
    if ($segments -notcontains $Bin) {
        [Environment]::SetEnvironmentVariable('Path', ((@($segments) + $Bin) -join ';'), 'User')
        Write-Host "PATH updated with $Bin (open a new terminal)"
    }
}
$env:Path = "$Bin;$env:Path"

Write-Host "`n Installation complete"
Write-Host "  api:   $BaseUrl"
Write-Host "`nStart Codex with: xingchi-codex"
Write-Host 'Choose your model and reasoning level with /model in Codex.'
Write-Host 'Check the setup with: xingchi'
