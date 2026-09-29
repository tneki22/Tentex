# Запуск Tentex «как после первой установки»: отдельный worktree, пустая база,
# свои порты и свой compose-проект. Основной стенд (5173/8000) не затрагивается.
#
#   .\scripts\fresh.ps1 up      поднять (по умолчанию)
#   .\scripts\fresh.ps1 down    остановить, данные остаются
#   .\scripts\fresh.ps1 reset   убрать текущие данные в архив и начать с чистой базы
#   .\scripts\fresh.ps1 sync    влить свежий main в эту ветку и пересобрать
#   .\scripts\fresh.ps1 logs    логи (можно указать сервис: logs api)
#   .\scripts\fresh.ps1 status  контейнеры и адреса

param(
    [ValidateSet("up", "down", "reset", "sync", "logs", "status")]
    [string]$Command = "up",
    [string]$Service = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$web = 5273
$api = 8100
$searx = 8988

# .env не в git: compose читает из него порты и имя проекта.
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    @"
COMPOSE_PROJECT_NAME=tentex-fresh
TENTEX_WEB_PORT=$web
TENTEX_API_PORT=$api
TENTEX_SEARXNG_PORT=$searx
"@ | Set-Content $envFile -Encoding utf8
}

function Show-Urls {
    Write-Host "Интерфейс: http://localhost:$web"
    Write-Host "API:       http://localhost:$api/docs"
    Write-Host "Данные:    $(Join-Path $root 'data')"
}

function Start-Fresh {
    docker compose up -d --build
    Write-Host "Жду, пока api станет healthy..."
    for ($i = 0; $i -lt 60; $i++) {
        $state = docker inspect --format "{{.State.Health.Status}}" (docker compose ps -q api) 2>$null
        if ($state -eq "healthy") { break }
        Start-Sleep -Seconds 3
    }
    docker compose ps
    Show-Urls
}

switch ($Command) {
    "up" { Start-Fresh }
    "down" { docker compose down }
    "logs" {
        if ($Service) { docker compose logs -f --tail 100 $Service }
        else { docker compose logs -f --tail 100 }
    }
    "status" { docker compose ps; Show-Urls }
    "reset" {
        docker compose down
        $data = Join-Path $root "data"
        if (Test-Path $data) {
            # Данные не удаляем, а откладываем: в архиве можно вернуть чужую работу.
            $archive = Join-Path (Split-Path $root -Parent) "_fresh-archive"
            New-Item -ItemType Directory -Force $archive | Out-Null
            $target = Join-Path $archive (Get-Date -Format "yyyyMMdd-HHmmss")
            Move-Item $data $target
            Write-Host "Старые данные перенесены: $target"
        }
        Start-Fresh
    }
    "sync" {
        if (git status --porcelain) {
            throw "В ветке есть незакоммиченные изменения — сначала закоммить или отложи."
        }
        git merge main
        Start-Fresh
    }
}
