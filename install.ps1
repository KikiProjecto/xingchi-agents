# xingchi-codex installer for Windows.
# Points the Codex CLI at the Xingchi upstream (OpenAI Responses API).
# No local proxy, one key.
#requires -version 5.1
param(
    [switch]$Yes,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'

$Repo = if ($env:XINGCHI_REPO) { $env:XINGCHI_REPO } else { 'kikiprojecto/xingchi-codex' }
$Branch = if ($env:XINGCHI_BRANCH) { $env:XINGCHI_BRANCH } else { 'main' }
$XDir = if ($env:XINGCHI_HOME) { $env:XINGCHI_HOME } else { Join-Path $env:USERPROFILE '.xingchi' }
$Bin = if ($env:XINGCHI_BIN) { $env:XINGCHI_BIN } else { Join-Path $env:LOCALAPPDATA 'xingchi\bin' }
$Upstream = if ($env:XINGCHI_UPSTREAM) { $env:XINGCHI_UPSTREAM } else { 'https://api.xingchiapi.com/v1' }
$Model = 'gpt-6.1-sol'
$UpstreamKeyFile = Join-Path $XDir 'upstream.key'

if ($Help) {
    Write-Host "usage: install.ps1 [-Yes]`n"
    Write-Host "Configures the Codex CLI for the Xingchi upstream (model $Model)."
    Write-Host "Stores your Xingchi API key in $UpstreamKeyFile (mode 600) and writes"
    Write-Host "~/.codex/config.toml to use $Upstream.`n"
    Write-Host "  -Yes    never prompt; requires XINGCHI_API_KEY"
    return
}

$SelfDir = $PSScriptRoot
if (-not $SelfDir -or -not (Test-Path (Join-Path $SelfDir 'lib\config.py'))) {
    $tmp = Join-Path $env:TEMP ("xingchi-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'src.zip'
    Write-Host "download $Repo ($Branch)..."
    Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    $childArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $src.FullName 'install.ps1'))
    if ($Yes) { $childArgs += '-Yes' }
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

Write-Host "`n[1/4] Xingchi API key"
$upstream = $env:XINGCHI_API_KEY
if (-not $upstream -and (Test-Path $UpstreamKeyFile)) {
    $upstream = (Get-Content $UpstreamKeyFile -Raw).Trim()
}
if (-not $upstream) {
    if ($Yes) { throw 'set XINGCHI_API_KEY (your xingchiapi key) or run without -Yes' }
    Write-Host "`nCreate a key at https://xingchiapi.com/keys, copy it, then paste it here (input is hidden)."
    $secure = Read-Host 'Paste your xingchiapi API key' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $upstream = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::FreeBSTR($bstr)
    }
}
# Pasting from a browser can carry spaces or CR; trim or the key fails with 401.
$upstream = "$upstream".Trim()
if (-not $upstream) { throw 'empty API key' }
[IO.File]::WriteAllText($UpstreamKeyFile, "$upstream`n")

Write-Host "`n[2/4] Codex CLI"
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    Write-Host '  codex not found, installing @openai/codex...'
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
}

Write-Host "`n[3/4] Configuring Codex and installing launchers"
$env:XINGCHI_API_KEY = $upstream
$env:XINGCHI_UPSTREAM = $Upstream
$env:XINGCHI_HOME = $XDir
& $python (Join-Path $SelfDir 'lib\config.py') codex
if ($LASTEXITCODE -ne 0) { throw 'config for codex failed' }

$xingchiCmd = @"
@echo off
setlocal
set "XINGCHI_KEY_FILE=$UpstreamKeyFile"
if not exist "%XINGCHI_KEY_FILE%" (
  echo error: API key missing at "%XINGCHI_KEY_FILE%" 1>&2
  exit /b 1
)
set /p OPENAI_API_KEY=<"%XINGCHI_KEY_FILE%"
set "OPENAI_BASE_URL=$Upstream"
codex %*
"@
[IO.File]::WriteAllText((Join-Path $Bin 'xingchi-codex.cmd'), $xingchiCmd + "`r`n")

$statusCmd = @"
@echo off
echo API:   $Upstream (direct, OpenAI Responses)
echo model: $Model
if exist "$UpstreamKeyFile" (echo key     set) else (echo key     missing)
where codex >NUL 2>&1
if errorlevel 1 (echo codex   missing) else (echo codex   installed)
echo.
echo start with: xingchi-codex
"@
[IO.File]::WriteAllText((Join-Path $Bin 'xingchi.cmd'), $statusCmd + "`r`n")

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$Bin*") {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $Bin), 'User')
    Write-Host "PATH updated with $Bin (open a new terminal)"
}
$env:Path = "$Bin;$env:Path"

Write-Host "`n[4/4] Verification"
$verifyFailed = $false
try {
    $headers = @{ Authorization = "Bearer $upstream"; 'User-Agent' = 'codex_cli_rs/0.170.0' }
    $models = Invoke-RestMethod -Uri "$Upstream/models" -Headers $headers -TimeoutSec 20
    Write-Host '  [OK] key accepted; upstream offers:'
    $models | ConvertTo-Json -Compress -Depth 4 | Write-Host
} catch {
    $status = 0
    try { $status = [int]$_.Exception.Response.StatusCode } catch { }
    if ($status -eq 401 -or $status -eq 403) {
        Write-Host "  [FAIL] upstream returned $status`: the key was rejected"
        $verifyFailed = $true
    } else {
        Write-Host "  [INFO] could not reach upstream /models; key not verified ($($_.Exception.Message))"
    }
}
if ($verifyFailed) {
    Write-Host "`nConfiguration was written, but the key does not work."
    Write-Host 'Get a working key at https://xingchiapi.com/keys and re-run the installer.'
    exit 1
}

Write-Host "`n Installation complete"
Write-Host "  model: $Model"
Write-Host "  api:   $Upstream"
Write-Host "`nStart Codex with: xingchi-codex"
Write-Host 'Check the setup with: xingchi'
