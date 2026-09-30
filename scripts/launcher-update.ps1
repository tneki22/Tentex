# Обновление не требует Git для установки из ZIP. Источник — main этого проекта.
$script:UpdateRepository = 'tneki22/Tentex'
$script:UpdateBranch = 'main'
# Архив исходников не содержит моделей; предел защищает от ошибочного пакета.
$script:MaxArchiveBytes = 2GB

function Resolve-SourcePath {
    <# Все записи и удаления ограничены явно выбранной папкой, без junction. #>
    param([string]$Root, [string]$Relative)
    $segments = $Relative.Replace('\', '/').Split('/')
    if ([IO.Path]::IsPathRooted($Relative) -or -not $Relative -or
        @($segments | Where-Object { $_ -in @('', '.', '..') -or $_ -match '[<>:"|?*\x00-\x1f]' -or $_ -match '[ .]$' }).Count) {
        throw "Недопустимый путь в обновлении: $Relative"
    }
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $path = [IO.Path]::GetFullPath((Join-Path $rootPath $Relative))
    if (-not $path.StartsWith($rootPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Путь выходит из папки установки: $Relative"
    }
    $probe = $path
    while ($probe.Length -gt $rootPath.Length) {
        if (Test-Path -LiteralPath $probe) {
            if ((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Обновление не проходит через ссылку: $probe"
            }
        }
        $probe = Split-Path $probe -Parent
    }
    return $path
}

function Test-ProtectedSourcePath {
    param([string]$Relative)
    $segments = $Relative.Replace('\', '/').Split('/')
    $protectedDirectories = @($script:IgnoredDirectories | Where-Object { $_ -notin @('.claude', '.vscode', '.idea') })
    return (@($segments | Where-Object { $_ -in $protectedDirectories }).Count -gt 0 -or
        $segments[-1] -match '^\.env($|\.(?!example$))' -or $segments[-1] -match '\.(key|sqlite(-wal|-shm)?)$')
}

function Expand-SourceArchive {
    <# Проверка всех путей до извлечения; Zip Slip и симлинки не попадают в установку. #>
    param([string]$Archive, [string]$Destination)
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $files = @($zip.Entries | Where-Object { -not $_.FullName.EndsWith('/') })
        $prefixes = @($files | ForEach-Object { $_.FullName.Split('/')[0] } | Sort-Object -Unique)
        if ($prefixes.Count -ne 1) { throw 'В ZIP ожидается одна корневая папка проекта.' }
        $total = 0L
        $seen = @{}
        foreach ($entry in $files) {
            $relative = $entry.FullName.Substring($prefixes[0].Length + 1).Replace('\', '/')
            $target = Resolve-SourcePath $Destination $relative
            if ($seen.ContainsKey($relative)) { throw "Повтор пути в ZIP: $relative" }
            $seen[$relative] = $true
            if (($entry.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000) { throw 'ZIP содержит символьную ссылку.' }
            $total += $entry.Length
            if ($total -gt $script:MaxArchiveBytes) { throw 'Архив исходников больше допустимого размера.' }
            if (Test-ProtectedSourcePath $relative) { throw "ZIP содержит данные или локальные настройки: $relative" }
        }
        foreach ($entry in $files) {
            $relative = $entry.FullName.Substring($prefixes[0].Length + 1).Replace('\', '/')
            $target = Resolve-SourcePath $Destination $relative
            New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target)
        }
    } finally { $zip.Dispose() }
    foreach ($required in @('docker-compose.yml', 'backend/app/main.py', 'frontend/package.json', 'scripts/launcher.ps1')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Destination $required))) { throw "В обновлении отсутствует $required. Возможно, запускатор ещё не опубликован в main." }
    }
}

function Assert-ArchiveUnmodified {
    param([object[]]$Baseline, [object[]]$Incoming)
    $known = @{}
    foreach ($file in $Baseline) {
        $known[$file.path] = $true
        $path = Resolve-SourcePath $script:ProjectRoot $file.path
        if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $file.hash) {
            throw "Есть локальная правка: $($file.path). Обновление остановлено; сохраните правку отдельно или восстановите исходный файл."
        }
    }
    foreach ($file in $Incoming) {
        $path = Resolve-SourcePath $script:ProjectRoot $file.path
        if (-not $known.ContainsKey($file.path) -and (Test-Path -LiteralPath $path)) {
            throw "Новый файл обновления совпал с локальным: $($file.path). Перенесите локальный файл отдельно."
        }
    }
}

function Copy-SourceFiles {
    param([string]$From, [string]$To, [object[]]$Manifest)
    foreach ($file in $Manifest) {
        $source = Resolve-SourcePath $From $file.path
        $target = Resolve-SourcePath $To $file.path
        New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}

function Install-ArchiveSource {
    <# Снимок старых исходников позволяет восстановиться при ошибке копирования. #>
    param([string]$Staged, [string]$Backup, [object[]]$Baseline, [object[]]$Incoming)
    $sourceBackup = Join-Path $Backup 'source'
    Copy-SourceFiles $script:ProjectRoot $sourceBackup $Baseline
    Save-Json (Join-Path $Backup 'source-manifest.json') $Baseline
    $newPaths = @{}
    foreach ($file in $Incoming) { $newPaths[$file.path] = $true }
    try {
        Copy-SourceFiles $Staged $script:ProjectRoot $Incoming
        foreach ($file in $Baseline) {
            if (-not $newPaths.ContainsKey($file.path)) {
                Remove-Item -LiteralPath (Resolve-SourcePath $script:ProjectRoot $file.path)
            }
        }
    } catch {
        $copyError = $_
        $oldPaths = @{}
        foreach ($file in $Baseline) { $oldPaths[$file.path] = $true }
        foreach ($file in $Incoming) {
            $path = Resolve-SourcePath $script:ProjectRoot $file.path
            if (-not $oldPaths.ContainsKey($file.path) -and (Test-Path -LiteralPath $path)) { Remove-Item -LiteralPath $path }
        }
        Copy-SourceFiles $sourceBackup $script:ProjectRoot $Baseline
        throw "Замена исходников не завершена; прежние файлы восстановлены. $($copyError.Exception.Message)"
    }
    Save-Json (Join-Path $script:StateDirectory 'source-manifest.json') $Incoming
}

function Get-GitUpdate {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Это Git-клон. Для его обновления нужен Git: https://git-scm.com/downloads/win' }
    $dirty = Invoke-Native git @('status', '--porcelain') -Capture
    if ($dirty) { throw "Есть локальные изменения. Обновление их не перезаписывает. Сначала сохраните их коммитом или отдельно.`n$dirty" }
    try { $upstream = Invoke-Native git @('rev-parse', '--abbrev-ref', '@{upstream}') -Capture }
    catch { throw 'У текущей ветки нет upstream. Настройте его в Git; для применения локальных правок достаточно файла запуска.' }
    Write-Host "Получаю обновления ветки $upstream..."
    Invoke-Native git @('fetch')
    $before = Invoke-Native git @('rev-parse', 'HEAD') -Capture
    $after = Invoke-Native git @('rev-parse', '@{upstream}') -Capture
    if ($before -eq $after) { return $null }
    try { $null = Invoke-Native git @('merge-base', '--is-ancestor', 'HEAD', '@{upstream}') -Capture }
    catch { throw 'История локальной ветки отличается от upstream. Обновление остановлено; объедините изменения вручную в Git.' }
    return [pscustomobject]@{ before = $before; after = $after }
}

function Get-ArchiveUpdate {
    param([string]$Workspace)
    Write-Host "Проверяю $script:UpdateRepository, ветку $script:UpdateBranch..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $headers = @{ 'User-Agent' = 'Tentex-launcher'; Accept = 'application/vnd.github+json' }
    try {
        $commit = Invoke-RestMethod "https://api.github.com/repos/$script:UpdateRepository/commits/$script:UpdateBranch" -Headers $headers -TimeoutSec 30
        if ($commit.sha -notmatch '^[0-9a-f]{40}$') { throw 'GitHub вернул некорректную версию.' }
        $versionFile = Join-Path $script:StateDirectory 'archive-version.txt'
        if ((Test-Path -LiteralPath $versionFile) -and (Get-Content -LiteralPath $versionFile -Raw).Trim() -eq $commit.sha) { return $null }
        $archive = Join-Path $Workspace 'update.zip'
        Invoke-WebRequest "https://codeload.github.com/$script:UpdateRepository/zip/$($commit.sha)" -Headers $headers -OutFile $archive -UseBasicParsing -TimeoutSec 300
    } catch {
        throw "Не удалось скачать обновление. Проверьте интернет и доступность публичного репозитория $script:UpdateRepository. Текущая версия сохранена. $($_.Exception.Message)"
    }
    $staged = Join-Path $Workspace 'downloaded-source'
    Expand-SourceArchive $archive $staged
    return [pscustomobject]@{ staged = $staged; version = $commit.sha }
}

function Update-Tentex {
    param([switch]$NoBrowser)
    $workspace = Join-Path $script:StateDirectory ('updates/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $workspace -Force | Out-Null
    $isGit = Test-Path -LiteralPath (Join-Path $script:ProjectRoot '.git')
    if ($isGit) { $update = Get-GitUpdate }
    else {
        $update = Get-ArchiveUpdate $workspace
        if ($update) {
            # PowerShell 5.1 отдаёт JSON-массив одним объектом конвейера.
            $baseline = Get-Content -LiteralPath (Join-Path $script:StateDirectory 'source-manifest.json') -Raw | ConvertFrom-Json
            $incoming = @(Get-SourceManifest $update.staged)
            Assert-ArchiveUnmodified $baseline $incoming
        }
    }
    if (-not $update) {
        Write-Host 'Новых обновлений нет.'
        Start-Tentex -NoBrowser:$NoBrowser
        return
    }
    $null = Get-LaunchConfig
    Invoke-Compose @('stop', '--timeout', '60')
    Backup-UpdateData $workspace
    if ($isGit) {
        if ((Invoke-Native git @('status', '--porcelain') -Capture) -or
            (Invoke-Native git @('rev-parse', 'HEAD') -Capture) -ne $update.before) {
            throw 'Локальная ветка изменилась во время обновления. Код не заменён; копия данных сохранена.'
        }
        Save-Json (Join-Path $workspace 'git-version.json') $update
        Invoke-Native git @('merge', '--ff-only', $update.after)
    } else {
        Assert-ArchiveUnmodified $baseline $incoming
        Install-ArchiveSource $update.staged $workspace $baseline $incoming
        Set-Content -LiteralPath (Join-Path $script:StateDirectory 'archive-version.txt') -Value $update.version -Encoding ASCII
    }
    Write-Host "Версия обновлена. Копия перед обновлением: $workspace"
    Write-Host 'Если сборка не завершится, исправьте указанную ошибку и повторите запуск. Копия остаётся на месте.'
    Start-Tentex -NoBrowser:$NoBrowser -ForceBuild
}
