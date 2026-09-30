# Общие операции запускатора. Совместимо с Windows PowerShell 5.1.
Set-StrictMode -Version 2.0

# Время на холодный запуск Docker и тяжёлых сервисов; не лимит сборки образов.
$script:ReadyTimeoutSeconds = 240
$script:PollSeconds = 2
$script:IgnoredDirectories = @(
    '.git', '.worktrees', '.claude', '.tentex-launcher', 'data', 'node_modules',
    'dist', '.venv', 'venv', '__pycache__', '.pytest_cache', '.ruff_cache',
    '.mypy_cache', '.vite', 'test-results', 'playwright-report', 'htmlcov',
    '.idea', '.vscode', 'virtex', 'output', '.codebase-memory'
)

function Invoke-Native {
    <# Проверять exit code нужно явно: PowerShell 5.1 не считает его исключением. #>
    param([string]$Tool, [string[]]$Arguments, [switch]$Capture)
    $previousPreference = $ErrorActionPreference
    $output = @()
    $ErrorActionPreference = 'Continue'
    try {
        if ($Capture) {
            $output = @(& $Tool @Arguments 2>&1 | ForEach-Object { $_.ToString() })
        } else {
            & $Tool @Arguments 2>&1 | ForEach-Object { Write-Host $_.ToString() }
        }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($code -ne 0) {
        throw "$Tool завершился с кодом $code. $($output -join [Environment]::NewLine)"
    }
    if ($Capture) { return ($output -join [Environment]::NewLine) }
}

function Invoke-Compose {
    param([string[]]$Arguments, [switch]$Capture)
    Invoke-Native 'docker' (@('compose', '--project-directory', $script:ProjectRoot,
        '-f', (Join-Path $script:ProjectRoot 'docker-compose.yml')) + $Arguments) -Capture:$Capture
}

function Get-ProjectFiles {
    <# Не заходим в модели, node_modules и junction: запуск не зависит от их размера. #>
    param([string]$Directory, [string]$Prefix = '')
    foreach ($item in Get-ChildItem -LiteralPath $Directory -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        $relative = $Prefix + $item.Name
        if ($item.PSIsContainer) {
            if ($item.Name -notin $script:IgnoredDirectories) {
                Get-ProjectFiles $item.FullName ($relative + '/')
            }
        } elseif ($item.Name -notmatch '^(\.env(\.(?!example$).*)?$|TODO\.md|\.coverage|Thumbs\.db|\.DS_Store)$' -and
                  $item.Name -notmatch '\.(pyc|pyo|tsbuildinfo|key|sqlite(-wal|-shm)?)$') {
            $relative
        }
    }
}

function Get-SourceManifest {
    param([string]$Directory)
    foreach ($relative in @(Get-ProjectFiles $Directory | Sort-Object)) {
        [pscustomobject]@{ path = $relative; hash = (Get-FileHash -LiteralPath (Join-Path $Directory $relative) -Algorithm SHA256).Hash }
    }
}

function Get-BuildFingerprint {
    param([object]$Config)
    $paths = @('docker-compose.yml')
    foreach ($directory in @('backend', 'frontend', 'searxng')) {
        $path = Join-Path $script:ProjectRoot $directory
        if (Test-Path -LiteralPath $path) { $paths += @(Get-ProjectFiles $path ($directory + '/')) }
    }
    $lines = @($paths | Sort-Object | Where-Object {
        $_ -notmatch '^(backend/(tests|scripts)/|frontend/.*\.(spec|test)\.)'
    } | ForEach-Object {
        $_ + ':' + (Get-FileHash -LiteralPath (Join-Path $script:ProjectRoot $_) -Algorithm SHA256).Hash
    })
    # Смена портов/volume/environment тоже должна применяться при запуске.
    $inputText = ($lines -join "`n") + ($Config | ConvertTo-Json -Depth 30 -Compress)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($inputText)))).Replace('-', '')
    } finally { $algorithm.Dispose() }
}

function Save-Json {
    param([string]$Path, [object]$Value)
    $Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Initialize-ArchiveBaseline {
    # ZIP не содержит .git. Отпечатки первой установки защищают её локальные правки.
    $baseline = Join-Path $script:StateDirectory 'source-manifest.json'
    if (-not (Test-Path -LiteralPath (Join-Path $script:ProjectRoot '.git')) -and
        -not (Test-Path -LiteralPath $baseline)) {
        Save-Json $baseline @(Get-SourceManifest $script:ProjectRoot)
    }
}

function Ensure-Docker {
    $osType = ''
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        foreach ($base in @($env:ProgramFiles, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
            $bin = Join-Path $base 'Docker\Docker\resources\bin'
            if (Test-Path -LiteralPath (Join-Path $bin 'docker.exe')) { $env:PATH = "$bin;$env:PATH" }
        }
        $userBin = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'
        if (Test-Path -LiteralPath (Join-Path $userBin 'docker.exe')) { $env:PATH = "$userBin;$env:PATH" }
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Установите Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/ . После установки запустите Docker Desktop один раз и повторите запуск Tentex.'
    }
    try { $osType = Invoke-Native docker @('info', '--format', '{{.OSType}}') -Capture }
    catch { Write-Host 'Docker выключен. Запускаю Docker Desktop...' }
    if ($osType -eq 'linux') { return }
    if ($osType -eq 'windows') { throw 'Переключите Docker Desktop в режим Linux containers и повторите запуск.' }
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
    )
    $desktop = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($desktop) { Start-Process -FilePath $desktop -WindowStyle Hidden }
    $deadline = (Get-Date).AddSeconds($script:ReadyTimeoutSeconds)
    do {
        Start-Sleep -Seconds $script:PollSeconds
        try {
            $osType = Invoke-Native docker @('info', '--format', '{{.OSType}}') -Capture
            if ($osType -eq 'linux') { return }
            $lastDockerError = 'Нужен режим Linux containers.'
        }
        catch { $lastDockerError = $_.Exception.Message }
    } while ((Get-Date) -lt $deadline)
    throw "Docker не готов. Откройте Docker Desktop: проверьте WSL, виртуализацию и режим Linux containers. $lastDockerError"
}

function Get-LaunchConfig {
    $config = (Invoke-Compose @('config', '--format', 'json') -Capture) | ConvertFrom-Json
    $port = @($config.services.web.ports | Where-Object { $_.target -eq 5173 })
    $volume = @($config.services.api.volumes | Where-Object { $_.target -eq '/data' })
    if ($port.Count -ne 1 -or $volume.Count -ne 1 -or $volume[0].type -ne 'bind') {
        throw 'Запускатор ожидает один порт web:5173 и каталог данных api:/data в docker-compose.yml.'
    }
    $script:WebUrl = 'http://localhost:' + $port[0].published
    $script:DataDirectory = $volume[0].source
    return $config
}

function Test-RequiredImages {
    param([object]$Config)
    foreach ($service in $Config.services.PSObject.Properties) {
        $imageProperty = $service.Value.PSObject.Properties['image']
        $image = if ($imageProperty) { $imageProperty.Value } else { '' }
        if (-not $image) { $image = $Config.name + '-' + $service.Name }
        try { $null = Invoke-Native docker @('image', 'inspect', $image, '--format', '{{.Id}}') -Capture }
        catch { return $false }
    }
    return $true
}

function Wait-Tentex {
    $deadline = (Get-Date).AddSeconds($script:ReadyTimeoutSeconds)
    $lastProblem = 'Обработчик ещё запускается.'
    do {
        try {
            $health = Invoke-RestMethod "$script:WebUrl/api/health" -TimeoutSec 5
            $status = Invoke-RestMethod "$script:WebUrl/api/system/status" -TimeoutSec 10
            if ($health.status -eq 'ok' -and -not @($status.items | Where-Object { $_.code -eq 'worker_offline' }).Count) {
                $null = Invoke-WebRequest $script:WebUrl -UseBasicParsing -TimeoutSec 5
                return
            }
            $lastProblem = 'Фоновый обработчик не отвечает.'
        } catch { $lastProblem = $_.Exception.Message }
        Start-Sleep -Seconds $script:PollSeconds
    } while ((Get-Date) -lt $deadline)
    throw "Tentex не готов: $lastProblem Откройте файл диагностики."
}

function Start-Tentex {
    param([switch]$NoBrowser, [switch]$ForceBuild)
    $config = Get-LaunchConfig
    $fingerprint = Get-BuildFingerprint $config
    $fingerprintFile = Join-Path $script:StateDirectory 'build.sha256'
    $previous = if (Test-Path -LiteralPath $fingerprintFile) { (Get-Content -LiteralPath $fingerprintFile -Raw).Trim() } else { '' }
    $needsBuild = $ForceBuild -or $fingerprint -ne $previous -or -not (Test-RequiredImages $config)
    if ($needsBuild) {
        Write-Host 'Первая установка или изменился проект. Собираю образы; первый запуск требует интернета.'
        Invoke-Compose @('build')
        # SearXNG — готовый образ; уже установленный не скачиваем повторно.
        if (-not (Test-RequiredImages $config)) { Invoke-Compose @('pull', '--policy', 'missing', 'searxng') }
    } else { Write-Host 'Сборка актуальна. Запускаю без пересборки и скачивания образов.' }
    $startArguments = @('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', "$script:ReadyTimeoutSeconds")
    # Изменение смонтированных настроек SearXNG тоже требует перезапуска.
    if ($needsBuild) { $startArguments += '--force-recreate' }
    Invoke-Compose $startArguments
    Wait-Tentex
    # Отпечаток записывается только после успеха: неудачный запуск можно повторить.
    Set-Content -LiteralPath $fingerprintFile -Value $fingerprint -Encoding ASCII
    Write-Host "Tentex готов: $script:WebUrl"
    Write-Host "Данные: $script:DataDirectory"
    if (-not $NoBrowser) { Start-Process $script:WebUrl }
}

function Backup-UpdateData {
    <# Только после compose stop: SQLite, WAL и файлы копируются без писателей. #>
    param([string]$Destination)
    if (-not (Test-Path -LiteralPath $script:DataDirectory)) { return }
    Write-Host 'Сохраняю данные перед обновлением (без моделей и прежних резервных копий)...'
    $target = Join-Path $Destination 'data'
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $script:DataDirectory -Force) {
        if ($item.Name -in @('models', 'backups')) { continue }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "В данных обнаружена ссылка: $($item.FullName). Сделайте копию через Хранилище." }
        if ($item.PSIsContainer -and @(Get-ChildItem -LiteralPath $item.FullName -Recurse -Force | Where-Object {
            $_.Attributes -band [IO.FileAttributes]::ReparsePoint
        }).Count) { throw "В данных обнаружена вложенная ссылка: $($item.FullName). Сделайте копию через Хранилище." }
        Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
    }
    Write-Host "Копия данных: $target"
}
