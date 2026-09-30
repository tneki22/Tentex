<# Запуск, остановка, диагностика и обновление одной установки Tentex. #>
param(
    [ValidateSet('start', 'stop', 'update', 'status')]
    [string]$Command = 'start',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'launcher-common.ps1')
. (Join-Path $PSScriptRoot 'launcher-update.ps1')

function Invoke-Launcher {
    $script:ProjectRoot = Split-Path $PSScriptRoot -Parent
    $script:StateDirectory = Join-Path $script:ProjectRoot '.tentex-launcher'
    New-Item -ItemType Directory -Path $script:StateDirectory -Force | Out-Null
    $lock = $null
    $transcribing = $false
    try {
        # FileShare.None освобождается и при падении процесса; старый файл не блокирует.
        try {
            $lock = [IO.File]::Open((Join-Path $script:StateDirectory 'launcher.lock'),
                [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        } catch [IO.IOException] { throw 'Tentex уже запускается или обновляется. Дождитесь завершения открытого окна.' }
        $log = Join-Path $script:StateDirectory ("{0}-{1}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $Command)
        Start-Transcript -LiteralPath $log | Out-Null
        $transcribing = $true
        Set-Location -LiteralPath $script:ProjectRoot
        Write-Host "Tentex: $Command"
        Write-Host "Папка проекта: $script:ProjectRoot"
        Initialize-ArchiveBaseline
        Ensure-Docker
        $null = Invoke-Compose @('version') -Capture
        switch ($Command) {
            'start' { Start-Tentex -NoBrowser:$NoBrowser }
            'stop' {
                Invoke-Compose @('stop', '--timeout', '60')
                Write-Host 'Tentex остановлен. Проекты, материалы и модели сохранены.'
            }
            'update' { Update-Tentex -NoBrowser:$NoBrowser }
            'status' {
                $null = Get-LaunchConfig
                Invoke-Compose @('ps', '--all')
                Invoke-Compose @('logs', '--no-color', '--tail', '60')
                Write-Host "Интерфейс: $script:WebUrl"
                Write-Host "Данные: $script:DataDirectory"
                Write-Host "Диагностика сохранена: $log"
            }
        }
        return 0
    } catch {
        Write-Host "Ошибка: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host 'При занятом порте остановите другую установку или задайте TENTEX_WEB_PORT / TENTEX_API_PORT / TENTEX_SEARXNG_PORT в .env.'
        Write-Host "Журналы: $script:StateDirectory"
        return 1
    } finally {
        if ($transcribing) { Stop-Transcript | Out-Null }
        if ($lock) { $lock.Dispose() }
    }
}

# Dot-source используется точечными тестами и не запускает Docker.
if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-Launcher) }
