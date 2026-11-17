# xingchi-agents installer for Windows.
#requires -version 5.1
param(
    [string]$Agents = '',
    [switch]$Yes,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'

$Repo = if ($env:XINGCHI_REPO) { $env:XINGCHI_REPO } else { 'kikiprojecto/xingchi-agents' }
$Branch = if ($env:XINGCHI_BRANCH) { $env:XINGCHI_BRANCH } else { 'main' }
$XDir = if ($env:XINGCHI_HOME) { $env:XINGCHI_HOME } else { Join-Path $env:USERPROFILE '.xingchi' }
$Bin = if ($env:XINGCHI_BIN) { $env:XINGCHI_BIN } else { Join-Path $env:LOCALAPPDATA 'xingchi\bin' }
$AllAgents = @('claude', 'hermes', 'opencode', 'codex', 'pi', 'kilo', 'agy', 'gemini', 'openclaw')
$BridgeUrl = 'http://127.0.0.1:4010'

if ($Help) {
    Write-Host "usage: install.ps1 [-Agents LIST] [-Yes]`n"
    Write-Host "  -Agents LIST   comma or space separated names, or 'all'"
    Write-Host "  -Yes           never prompt; requires -Agents or XINGCHI_API_KEY"
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
    if ($Agents) { $childArgs += @('-Agents', $Agents) }
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

$venv = Join-Path $XDir 'venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$litellm = Join-Path $venv 'Scripts\litellm.exe'
if (-not (Test-Path $litellm)) {
    Write-Host "installing litellm[proxy] into $venv (one time)..."
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'python venv failed' }
    & $venvPython -m pip install -q --upgrade pip
    & $venvPython -m pip install -q 'litellm[proxy]'
    if ($LASTEXITCODE -ne 0) { throw 'litellm install failed' }
}

$upstreamKeyFile = Join-Path $XDir 'upstream.key'

$bridgeKeyFile = Join-Path $XDir 'bridge.key'
$bridge = ''
if (Test-Path $bridgeKeyFile) { $bridge = (Get-Content $bridgeKeyFile -Raw).Trim() }
if (-not $bridge -and (Test-Path (Join-Path $XDir 'litellm.yaml'))) {
    $m = Select-String -Path (Join-Path $XDir 'litellm.yaml') -Pattern '^\s*master_key:\s*(.+)$' | Select-Object -First 1
    if ($m) { $bridge = $m.Matches[0].Groups[1].Value.Trim() }
}
if (-not $bridge) {
    $hex = & $venvPython -c "import secrets; print(secrets.token_hex(24))"
    $bridge = "sk-xingchi-$hex"
}
[IO.File]::WriteAllText($bridgeKeyFile, "$bridge`n")

$litellmYaml = @"
model_list:
  - model_name: gpt-6-astra
    litellm_params:
      model: openai/gpt-6-astra
      api_base: https://api.xingchiapi.com/v1
      api_key: os.environ/XINGCHI_API_KEY
      extra_headers:
        user-agent: "opencode/0.9.0"
  - model_name: gpt-6.1-sol
    litellm_params:
      model: openai/gpt-6.1-sol
      api_base: https://api.xingchiapi.com/v1
      api_key: os.environ/XINGCHI_API_KEY
      extra_headers:
        user-agent: "opencode/0.9.0"

litellm_settings:
  # gpt-6-astra rejects some parameters clients send (reasoning_effort).
  drop_params: true

general_settings:
  master_key: $bridge
  disable_model_info_refresh: true
"@
[IO.File]::WriteAllText((Join-Path $XDir 'litellm.yaml'), $litellmYaml)

$startCmd = @"
@echo off
set /p XINGCHI_API_KEY=<"$upstreamKeyFile"
"$litellm" --config "$XDir\litellm.yaml" --host 127.0.0.1 --port 4010
"@
[IO.File]::WriteAllText((Join-Path $XDir 'start.cmd'), $startCmd)

$envCmd = @"
@echo off
set "XINGCHI_BRIDGE_URL=$BridgeUrl"
set "XINGCHI_BRIDGE_KEY=$bridge"
"@
[IO.File]::WriteAllText((Join-Path $XDir 'env.cmd'), $envCmd)

$bridgeUpCmd = @"
@echo off
curl -fsS -o NUL --max-time 2 $BridgeUrl/health/liveliness >NUL 2>&1
if not errorlevel 1 exit /b 0
start "xingchi bridge" /min cmd /c ""$XDir\start.cmd""
set /a attempt=0
:wait
curl -fsS -o NUL --max-time 2 $BridgeUrl/health/liveliness >NUL 2>&1
if not errorlevel 1 exit /b 0
set /a attempt+=1
if %attempt% geq 120 (
  echo xingchi bridge did not start; run "$XDir\start.cmd" to see the error
  exit /b 1
)
timeout /t 1 /nobreak >NUL
goto wait
"@
[IO.File]::WriteAllText((Join-Path $Bin '_bridge-up.cmd'), $bridgeUpCmd)

function Get-AgentInvocation($agent) {
    switch ($agent) {
        'claude' { return "claude --settings `"$XDir\claude-settings.json`" %*" }
        'hermes' { return 'hermes --provider xingchi -m gpt-6-astra %*' }
        'opencode' { return 'opencode %*' }
        'codex' { return 'codex %*' }
        'pi' { return 'pi --provider xingchi --model gpt-6-astra %*' }
        'kilo' { return 'kilo %*' }
        'agy' { return 'agy %*' }
        'gemini' {
            return @(
                'set "GEMINI_API_KEY=%XINGCHI_BRIDGE_KEY%"',
                'set "GOOGLE_GEMINI_BASE_URL=%XINGCHI_BRIDGE_URL%"',
                'gemini -m gpt-6-astra %*'
            )
        }
        'openclaw' { return 'openclaw %*' }
    }
}

$hints = @{
    claude   = 'npm install -g @anthropic-ai/claude-code'
    hermes   = "iex (irm 'https://hermes-agent.nousresearch.com/install.ps1')"
    opencode = 'npm install -g opencode-ai'
    codex    = 'npm install -g @openai/codex'
    pi       = 'npm install -g @earendil-works/pi-coding-agent'
    kilo     = 'npm install -g @kilocode/cli'
    agy      = "iex (irm 'https://antigravity.google/cli/install.ps1')"
    gemini   = 'npm install -g @google/gemini-cli'
    openclaw = 'npm install -g openclaw'
}

$npmPackages = @{
    claude   = '@anthropic-ai/claude-code'
    opencode = 'opencode-ai'
    codex    = '@openai/codex'
    pi       = '@earendil-works/pi-coding-agent'
    kilo     = '@kilocode/cli'
    gemini   = '@google/gemini-cli'
    openclaw = 'openclaw'
}

function Install-AgentCli($agent) {
    if (Get-Command $agent -ErrorAction SilentlyContinue) { return }
    Write-Host "installing $agent..."
    $pkg = $npmPackages[$agent]
    if ($pkg) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue) -and (Get-Command winget -ErrorAction SilentlyContinue)) {
            Write-Host 'installing Node.js...'
            winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements --silent
            $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
        }
        if (Get-Command npm -ErrorAction SilentlyContinue) { & npm install -g $pkg }
    } elseif ($agent -eq 'hermes') {
        & powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (irm 'https://hermes-agent.nousresearch.com/install.ps1')"
    } elseif ($agent -eq 'agy') {
        & powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (irm 'https://antigravity.google/cli/install.ps1')"
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $extraDirs = @((Join-Path $env:USERPROFILE '.local\bin'), (Join-Path $env:LOCALAPPDATA 'agy\bin'))
    foreach ($dir in $extraDirs) { if ((Test-Path $dir) -and ($env:Path -notlike "*$dir*")) { $env:Path = "$dir;$env:Path" } }
    if (Get-Command $agent -ErrorAction SilentlyContinue) {
        Write-Host "  installed $agent"
    } else {
        Write-Host "  note: $agent still missing. Install: $($hints[$agent])"
    }
}

$installedAgents = @($AllAgents | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue })
$default = if ($installedAgents.Count -gt 0) { $installedAgents } else { $AllAgents }

function Resolve-Selection($input) {
    if (-not $input) { return $default }
    if ($input -eq 'all' -or $input -eq 'a') { return $AllAgents }
    $picked = @()
    foreach ($token in ($input -split '[,\s]+' | Where-Object { $_ })) {
        if ($token -match '^\d+$') {
            $n = [int]$token
            if ($n -lt 1 -or $n -gt $AllAgents.Count) { throw "no agent $token" }
            $name = $AllAgents[$n - 1]
        } else {
            $name = $token
        }
        if ($AllAgents -notcontains $name) { throw "unknown agent: $token" }
        $picked += $name
    }
    return $picked
}

if ($Agents) {
    $selected = Resolve-Selection $Agents
} elseif ($Yes) {
    $selected = $default
} else {
    Write-Host "`nCHOOSE AGENTS YOU WANT TO SET:"
    for ($i = 0; $i -lt $AllAgents.Count; $i++) {
        $state = if (Get-Command $AllAgents[$i] -ErrorAction SilentlyContinue) { 'installed' } else { 'missing' }
        Write-Host ("  {0}) {1,-9} [{2}]" -f ($i + 1), $AllAgents[$i], $state)
    }
    $answer = Read-Host ("`nNumbers, names or 'all' (blank = {0})" -f ($default -join ','))
    $selected = Resolve-Selection $answer
}
if (-not $selected -or $selected.Count -eq 0) { throw 'no agents selected' }

$upstream = $env:XINGCHI_API_KEY
if (-not $upstream -and (Test-Path (Join-Path $XDir 'key'))) {
    $upstream = (Get-Content (Join-Path $XDir 'key') -Raw).Trim()
}
if (-not $upstream -and (Test-Path $upstreamKeyFile)) {
    $upstream = (Get-Content $upstreamKeyFile -Raw).Trim()
}
if (-not $upstream) {
    if ($Yes) { throw 'set XINGCHI_API_KEY (your xingchiapi key) or run without -Yes' }
    Write-Host "`nCreate a key at https://xingchiapi.com/keys, copy it, then paste it here (input is hidden)."
    $secure = Read-Host 'Paste your xingchiapi API key' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $upstream = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}
if (-not $upstream) { throw 'empty API key' }
[IO.File]::WriteAllText($upstreamKeyFile, "$upstream`n")

$env:XINGCHI_BRIDGE_KEY = $bridge
$env:XINGCHI_URL = $BridgeUrl
$env:XINGCHI_HOME = $XDir

foreach ($agent in $selected) {
    Install-AgentCli $agent
    if ($agent -eq 'hermes' -and -not (Test-Path (Join-Path $env:USERPROFILE '.hermes\config.yaml'))) {
        Write-Host "skip hermes: run 'hermes' once to create ~\.hermes\config.yaml, then re-run"
        continue
    }
    & $venvPython (Join-Path $SelfDir 'lib\config.py') $agent
    if ($LASTEXITCODE -ne 0) { throw "config for $agent failed" }
    $lines = @(
        '@echo off',
        "call `"$XDir\env.cmd`"",
        "call `"$Bin\_bridge-up.cmd`"",
        'if errorlevel 1 exit /b 1'
    ) + (Get-AgentInvocation $agent)
    [IO.File]::WriteAllText((Join-Path $Bin "xingchi-$agent.cmd"), ($lines -join "`r`n") + "`r`n")
}

$statusCmd = @"
@echo off
call "$XDir\env.cmd"
curl -fsS -o NUL --max-time 2 $BridgeUrl/health/liveliness >NUL 2>&1
if errorlevel 1 (echo bridge: down) else (echo bridge: up)
for %%a in (claude hermes opencode codex pi kilo agy gemini openclaw) do (
  where %%a >NUL 2>&1
  if errorlevel 1 (echo %%a missing) else (echo %%a installed)
)
"@
[IO.File]::WriteAllText((Join-Path $Bin 'xingchi.cmd'), $statusCmd)

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$Bin*") {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $Bin), 'User')
    Write-Host "PATH updated with $Bin (open a new terminal)"
}
$env:Path = "$Bin;$env:Path"

Write-Host "`nstarting bridge..."
& (Join-Path $Bin '_bridge-up.cmd') | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host 'bridge check: failed to start' }
else {
    try {
        $body = '{"model":"gpt-6-astra","messages":[{"role":"user","content":"Reply with OK"}],"max_tokens":4}'
        Invoke-RestMethod -Uri "$BridgeUrl/v1/chat/completions" -Method Post `
            -Headers @{ Authorization = "Bearer $bridge" } `
            -ContentType 'application/json' -Body $body -TimeoutSec 60 | Out-Null
        Write-Host 'bridge check: OK'
    } catch {
        Write-Host "bridge check: upstream failed: $($_.Exception.Message)"
    }
}

Write-Host "`ndone. configured: $($selected -join ', ')"
Write-Host 'start an agent with: xingchi-claude | xingchi-pi | xingchi-gemini ...'
Write-Host 'status: xingchi'
