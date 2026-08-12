# Диагностика связки OpenClaw + Telegram + движок модели. Windows / PowerShell.
#
#   powershell -ExecutionPolicy Bypass -File openclaw\diagnose.ps1
#
# Скрипт ничего не меняет — только читает.

$ErrorActionPreference = "Continue"
$script:Problems = 0

function Section($t) { Write-Host "`n──────────────────────────────────────────────────────" ; Write-Host $t ; Write-Host "──────────────────────────────────────────────────────" }
function Ok($m)   { Write-Host "[ OK ]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "[FAIL] $m" -ForegroundColor Red; $script:Problems++ }
function Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Inf($m)  { Write-Host "[INFO] $m" -ForegroundColor Cyan }

$cfg = if ($env:OPENCLAW_CONFIG_PATH) { $env:OPENCLAW_CONFIG_PATH } else { Join-Path $env:USERPROFILE ".openclaw\openclaw.json" }

# ── 1. Node.js ────────────────────────────────────────────────────────────
Section "1. Node.js"
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nv = (node -v).TrimStart('v')
    $major = [int]($nv.Split('.')[0])
    Inf "Установлен Node $nv"
    if ($major -ge 26)      { Ok "Версия подходит (рекомендуемая — 26)" }
    elseif ($major -ge 22)  { Ok "Версия скорее всего подходит (нужно 22.22.3+ / 24.15+ / 25.9+)" }
    else                    { Bad "Node слишком старый. Нужно 22.22.3+, 24.15+ или 25.9+ → https://nodejs.org/" }
} else {
    Bad "Node.js не найден. Установите с https://nodejs.org/"
}

# ── 2. OpenClaw CLI ───────────────────────────────────────────────────────
Section "2. OpenClaw CLI"
$oc = Get-Command openclaw -ErrorAction SilentlyContinue
if ($oc) {
    Ok "openclaw найден: $($oc.Source)"
    Inf "Версия: $(openclaw --version 2>&1 | Select-Object -First 1)"

    $all = @(Get-Command openclaw -All -ErrorAction SilentlyContinue)
    if ($all.Count -gt 1) {
        Warn "В системе несколько бинарников openclaw (split brain):"
        $all | ForEach-Object { Write-Host "       $($_.Source)" }
        Write-Host "       Частая причина 'сломалось после обновления'."
        Write-Host "       Лечение: почините PATH, затем: openclaw gateway install --force"
    }

    $touched = (openclaw config get meta.lastTouchedVersion 2>&1) -replace '"','' -replace '\s',''
    if ($touched) { Inf "Конфиг последний раз писала версия: $touched" }
} else {
    Bad "openclaw не найден в PATH → npm install -g openclaw@latest"
}

# ── 3. Конфиг ─────────────────────────────────────────────────────────────
Section "3. Конфиг openclaw.json"
if (Test-Path $cfg) {
    Ok "Найден: $cfg"
    $raw = Get-Content $cfg -Raw

    try { $null = $raw | ConvertFrom-Json; Ok "JSON валиден" }
    catch { Warn "JSON не парсится строго (допустимо, если это json5 с комментариями)" }

    if ($raw -match '11434/v1') {
        Bad "В конфиге Ollama указан baseUrl с /v1 — это legacy-режим"
        Write-Host '       OpenClaw ходит в НАТИВНЫЙ API Ollama (/api/chat).'
        Write-Host '       Исправьте на: "baseUrl": "http://127.0.0.1:11434", "api": "ollama"'
    }
    if ($raw -match '"ollama"' -and $raw -notmatch 'apiKey') {
        Warn "У провайдера ollama, похоже, не задан apiKey"
        Write-Host '       openclaw config set models.providers.ollama.apiKey "ollama-local"'
    }
    if ($raw -match 'ВСТАВЬТЕ|ВАШ_ЧИСЛОВОЙ|YOUR_TOKEN') {
        Bad "В конфиге остались placeholder-значения (токен / ID не подставлены)"
    }
} else {
    Bad "Конфиг не найден: $cfg"
    Write-Host "       Скопируйте шаблон: copy openclaw\configs\openclaw.llamacpp.json `"$cfg`""
}

# ── 4. Шлюз ───────────────────────────────────────────────────────────────
Section "4. Шлюз (gateway)"
if ($oc) {
    $gw = openclaw gateway status 2>&1 | Out-String
    $gw -split "`n" | Select-Object -First 20 | ForEach-Object { Write-Host "       $_" }
    if ($gw -match 'running') { Ok "Шлюз запущен" } else { Bad "Шлюз не в состоянии running → openclaw gateway restart" }
}
try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:18789" -TimeoutSec 5 -UseBasicParsing
    Ok "Порт 18789 отвечает (Control UI доступен)"
} catch { Warn "Порт 18789 не отвечает" }

# ── 5. Ollama ─────────────────────────────────────────────────────────────
Section "5. Движок: Ollama (порт 11434)"
if (Get-Command ollama -ErrorAction SilentlyContinue) { Inf "Установлен: $(ollama --version 2>&1 | Select-Object -First 1)" }
else { Inf "CLI ollama не найден (нормально, если вы перешли на llama.cpp)" }

try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    Ok "Демон Ollama отвечает"
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        $models = ollama list 2>&1 | Select-Object -Skip 1
        if ($models) {
            Ok "Скачанные модели:"
            $models | ForEach-Object { Write-Host "       $_" }
            Write-Host ""
            Write-Host "       ВАЖНО: имя модели в openclaw.json должно совпадать символ в символ."
        } else { Bad "Ollama работает, но моделей нет → ollama pull qwen3:8b" }
    }
} catch {
    Warn "Демон Ollama на 127.0.0.1:11434 не отвечает"
    Write-Host "       Проверьте иконку Ollama в трее или перезапустите службу."
    Write-Host "       (не проблема, если вы намеренно перешли на llama.cpp)"
}

if ($env:OLLAMA_API_KEY) { Ok "OLLAMA_API_KEY задан" }
else {
    Warn "OLLAMA_API_KEY не задан — без него провайдер ollama может не включиться"
    Write-Host '       setx OLLAMA_API_KEY "ollama-local"   (затем перезапустите терминал)'
}

# ── 6. llama.cpp ──────────────────────────────────────────────────────────
Section "6. Движок: llama.cpp (порт 8080)"
try {
    $lc = Invoke-RestMethod -Uri "http://127.0.0.1:8080/v1/models" -TimeoutSec 5
    Ok "llama-server отвечает на /v1/models"
    $lc.data | ForEach-Object { Write-Host "       id: $($_.id)" }
    Write-Host ""
    Write-Host "       Значение id должно совпадать с models.providers.llamacpp.models[].id"
} catch {
    Inf "llama-server на 127.0.0.1:8080 не запущен"
    Write-Host "       Запуск: openclaw\start-llama-server.bat"
}

# ── 7. Модели глазами OpenClaw ────────────────────────────────────────────
Section "7. Что видит сам OpenClaw"
if ($oc) { openclaw models status 2>&1 | Select-Object -First 25 | ForEach-Object { Write-Host "       $_" } }

# ── 8. Telegram ───────────────────────────────────────────────────────────
Section "8. Канал Telegram"
if ($oc) {
    openclaw channels status --probe 2>&1 | Select-Object -First 25 | ForEach-Object { Write-Host "       $_" }
    Write-Host ""
    Inf "Ожидающие подтверждения пары:"
    openclaw pairing list telegram 2>&1 | Select-Object -First 10 | ForEach-Object { Write-Host "       $_" }
}

$token = $env:TELEGRAM_BOT_TOKEN
if (-not $token -and (Test-Path $cfg)) {
    $m = [regex]::Match((Get-Content $cfg -Raw), '"botToken"\s*:\s*"([^"]+)"')
    if ($m.Success) { $token = $m.Groups[1].Value }
}
if ($token -and $token -notmatch 'ВСТАВЬТЕ') {
    try {
        $me = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getMe" -TimeoutSec 10
        if ($me.ok) { Ok "Токен бота валиден — @$($me.result.username)" }
        else        { Bad "Telegram отклонил токен (getMe != ok)" }
    } catch {
        Bad "Telegram отклонил токен или сеть недоступна: $($_.Exception.Message)"
        Write-Host "       Перевыпустите токен в @BotFather и обновите channels.telegram.botToken"
    }
} else {
    Inf "Токен не найден в конфиге/окружении — проверка getMe пропущена"
}

# ── 9. doctor ─────────────────────────────────────────────────────────────
Section "9. openclaw doctor"
if ($oc) { openclaw doctor 2>&1 | Select-Object -First 40 | ForEach-Object { Write-Host "       $_" } }

# ── Итог ──────────────────────────────────────────────────────────────────
Section "ИТОГ"
if ($script:Problems -eq 0) {
    Ok "Явных проблем не найдено."
    Write-Host ""
    Write-Host "Если бот всё ещё молчит — смотрите живые логи в момент отправки сообщения:"
    Write-Host "    openclaw logs --follow"
} else {
    Bad "Найдено проблем: $($script:Problems). Разбирайте сверху вниз — первая обычно и есть причина."
}

Write-Host ""
Write-Host "Стандартная последовательность починки:"
Write-Host "    openclaw doctor --fix"
Write-Host "    openclaw gateway restart"
Write-Host "    openclaw status --all"
Write-Host "    openclaw logs --follow"
