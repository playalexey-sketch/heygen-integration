# OpenClaw + Telegram: запуск без Ollama и починка Ollama

Инструкция на две части:

1. **[Часть 1](#часть-1--openclaw-в-telegram-без-ollama)** — поднять OpenClaw в Telegram **без Ollama**,
   на бесплатном движке с открытым кодом (llama.cpp), чтобы бот отвечал как раньше.
2. **[Часть 2](#часть-2--починить-старую-связку-на-ollama)** — починить старую связку **на Ollama**
   (пошаговая диагностика: где именно ломается).

Обе части можно держать одновременно: OpenClaw умеет иметь несколько провайдеров и
переключаться между ними командой `/model` прямо в чате Telegram.

---

## Сначала — важное про «Open WebUI»

Вы спросили про «WEB Open UI» (Open WebUI). Короткий ответ: **сам по себе он не заменит Ollama.**

| Что это | Роль | Может ли быть «мозгом» для OpenClaw |
|---|---|---|
| **Ollama** | движок инференса (запускает модель) | да |
| **llama.cpp / llama-server** | движок инференса, MIT, полностью открытый | **да — это и есть замена Ollama** |
| **LM Studio** | GUI-обёртка над llama.cpp | да (бесплатно, но само приложение закрытое) |
| **Open WebUI** | веб-**интерфейс** чата (фронтенд) | нет — ему самому нужен движок сзади (Ollama или llama.cpp) |

Open WebUI действительно отдаёт OpenAI-совместимый API (`POST /api/chat/completions`), то есть
технически OpenClaw к нему подключить можно ([доки Open WebUI](https://docs.openwebui.com/reference/api-endpoints/)).
Но это будет **прокси поверх движка**, а не замена движка: лишний слой, лишние поломки
tool-calling, и Ollama при этом чаще всего никуда не девается. Конфиг для этого варианта
я всё равно приложил — `configs/openclaw.openwebui.json` — но как основной путь **не рекомендую**.

**Вывод:** «бесплатно + открытый код + без Ollama» = **llama.cpp (`llama-server`)**.
Это тот же самый движок, который внутри Ollama и внутри LM Studio, только без обёртки.

---

## Часть 1 — OpenClaw в Telegram без Ollama

### TL;DR (примерно 15 минут)

```bash
# 1. Node 22.22.3+ / 24.15+ / 25.9+ (рекомендуется 26)
node -v

# 2. OpenClaw
npm install -g openclaw@latest        # или: curl -fsSL https://openclaw.ai/install.sh | bash

# 3. Движок модели вместо Ollama (llama.cpp)
#    Windows: скачать llama-<версия>-bin-win-*.zip из github.com/ggml-org/llama.cpp/releases
#    macOS:   brew install llama.cpp
#    Linux:   см. раздел ниже
llama-server -hf unsloth/Qwen3-8B-GGUF:Q4_K_M --jinja -c 32768 --port 8080 --alias local-model

# 4. Конфиг OpenClaw
#    скопировать openclaw/configs/openclaw.llamacpp.json → ~/.openclaw/openclaw.json
#    вписать туда botToken из @BotFather

# 5. Запуск
openclaw gateway restart
openclaw logs --follow
```

Дальше — то же самое, но по шагам и с объяснениями.

### Шаг 1. Node.js

OpenClaw требует Node **22.22.3+**, **24.15+** или **25.9+** (рекомендуемая — 26).
Очень частая причина «внезапно сломалось» — обновился Node или, наоборот, остался старый.

```bash
node -v
npm -v
```

Если версия ниже — поставьте LTS с [nodejs.org](https://nodejs.org/) (Windows) или через `nvm`.

### Шаг 2. Установка OpenClaw

**macOS / Linux:**
```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

**Windows (PowerShell):**
```powershell
iwr -useb https://openclaw.ai/install.ps1 | iex
```

**Любая ОС, через npm:**
```bash
npm install -g openclaw@latest
openclaw --version
```

### Шаг 3. Движок модели: llama.cpp вместо Ollama

`llama-server` — это HTTP-сервер из проекта [llama.cpp](https://github.com/ggml-org/llama.cpp)
(MIT-лицензия), который отдаёт OpenAI-совместимый `/v1/chat/completions`. Именно к нему
подключится OpenClaw.

**Установка:**

| ОС | Команда |
|---|---|
| macOS | `brew install llama.cpp` |
| Linux (Debian/Ubuntu) | `curl -fsSL https://raw.githubusercontent.com/ggml-org/llama.cpp/master/scripts/install-llama-cpp.sh \| bash`, либо готовые бинарники из [Releases](https://github.com/ggml-org/llama.cpp/releases) |
| Windows | Скачать `llama-<версия>-bin-win-cuda-x64.zip` (с NVIDIA) или `...-bin-win-cpu-x64.zip` из [Releases](https://github.com/ggml-org/llama.cpp/releases), распаковать, например, в `C:\llama` |

**Запуск сервера с моделью** (модель скачается с Hugging Face автоматически, один раз):

```bash
llama-server \
  -hf unsloth/Qwen3-8B-GGUF:Q4_K_M \
  --jinja \
  -c 32768 \
  --port 8080 \
  --host 127.0.0.1 \
  --alias local-model
```

Windows-вариант — готовый файл `openclaw/start-llama-server.bat`, Linux/macOS — `openclaw/start-llama-server.sh`.

Что означают ключи:

- `--jinja` — **обязательно**. Без него не работает function/tool calling, а OpenClaw без
  инструментов почти бесполезен.
- `-c 32768` — окно контекста. Системный промпт OpenClaw + описания инструментов сами по себе
  съедают 6–12 тыс. токенов, поэтому меньше 16k ставить нельзя.
- `--alias local-model` — фиксирует ID модели, чтобы он совпал с конфигом OpenClaw.

**Выбор модели под ваше железо:**

| RAM / VRAM | Модель | Строка `-hf` |
|---|---|---|
| 8 ГБ | Qwen3 4B | `unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` |
| 16 ГБ | **Qwen3 8B (рекомендую)** | `unsloth/Qwen3-8B-GGUF:Q4_K_M` |
| 24–32 ГБ | Qwen3 14B | `unsloth/Qwen3-14B-GGUF:Q4_K_M` |
| 32 ГБ+ | GPT-OSS 20B | `unsloth/gpt-oss-20b-GGUF:Q4_K_M` |

Модели меньше 7–8B на агентских задачах OpenClaw ведут себя плохо: путаются в инструментах и
обрезают контекст. Если железо слабое — честнее взять бесплатный облачный ключ
(см. [«Если железа не хватает»](#если-железа-не-хватает)).

**Проверка, что движок жив:**

```bash
curl http://127.0.0.1:8080/v1/models
curl http://127.0.0.1:8080/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"local-model","messages":[{"role":"user","content":"скажи: понг"}],"stream":false}'
```

### Шаг 4. Бот в Telegram

1. Откройте в Telegram **@BotFather** (проверьте, что хэндл именно такой).
2. `/newbot` → имя → username → получите токен вида `123456789:AAH...`.
3. Полезные настройки там же:
   - `/setprivacy` → **Disable**, если бот должен видеть все сообщения в группах
     (после смены — удалите и заново добавьте бота в группу);
   - `/setjoingroups` — разрешить/запретить добавление в группы.

Токен можно положить либо в конфиг (`channels.telegram.botToken`), либо в переменную
окружения `TELEGRAM_BOT_TOKEN`.

### Шаг 5. Конфиг OpenClaw

Конфиг живёт в `~/.openclaw/openclaw.json`
(Windows: `C:\Users\<Вы>\.openclaw\openclaw.json`).

Возьмите готовый файл из этого репозитория:

```bash
mkdir -p ~/.openclaw
cp openclaw/configs/openclaw.llamacpp.json ~/.openclaw/openclaw.json
```

И отредактируйте два места:

- `channels.telegram.botToken` — токен от BotFather;
- `channels.telegram.allowFrom` — ваш числовой Telegram user ID
  (узнать: напишите боту `/whoami` после первого запуска, или через @userinfobot).

Содержимое (кратко):

```json5
{
  models: {
    mode: "merge",
    providers: {
      llamacpp: {
        baseUrl: "http://127.0.0.1:8080/v1",   // /v1 обязателен
        apiKey: "sk-local",                    // llama.cpp ключ не проверяет
        api: "openai-completions",
        timeoutSeconds: 300,                   // локальная модель грузится медленно
        models: [{ id: "local-model", name: "Local (llama.cpp)", contextWindow: 32768, maxTokens: 4096 }]
      }
    }
  },
  agents: { defaults: { model: { primary: "llamacpp/local-model" } } },
  channels: {
    telegram: {
      enabled: true,
      botToken: "ВСТАВЬТЕ_ТОКЕН",
      dmPolicy: "allowlist",
      allowFrom: ["ВАШ_ЧИСЛОВОЙ_ID"]
    }
  }
}
```

Альтернатива вручную — через CLI:

```bash
openclaw onboard --non-interactive --accept-risk --skip-health \
  --auth-choice custom \
  --custom-base-url "http://127.0.0.1:8080/v1" \
  --custom-model-id "local-model"
```

### Шаг 6. Запуск и первый диалог

```bash
openclaw gateway install     # поставить как службу (по желанию)
openclaw gateway restart
openclaw gateway status      # ждём Runtime: running, порт 18789
openclaw logs --follow
```

Напишите боту в Telegram `/start`. Если `dmPolicy: "pairing"` — подтвердите доступ:

```bash
openclaw pairing list telegram
openclaw pairing approve telegram <КОД>     # код живёт 1 час
```

Проверить, что модель реально отвечает, минуя Telegram:

```bash
openclaw infer model run --model llamacpp/local-model --prompt "Reply with exactly: pong" --json
openclaw dashboard           # веб-панель на http://127.0.0.1:18789
```

### Если что-то не так на этом шаге

| Симптом | Причина | Лечение |
|---|---|---|
| `model_not_found` / 404 | `baseUrl` без `/v1` или `id` модели не совпал с `--alias` | привести в соответствие `curl :8080/v1/models` |
| Бот молчит, в логах ошибки про tools | сборка llama.cpp отдаёт `tool_calls.arguments` объектом вместо строки (известный баг) | обновить llama.cpp; если не помогло — в конфиге модели добавить `"compat": { "supportsTools": false }` |
| `messages[].content: expected a string` | бэкенд не принимает структурный контент | добавить `"compat": { "requiresStringContent": true }` |
| Первый ответ отваливается по таймауту | холодная загрузка модели | `timeoutSeconds: 300` уже стоит; поднимите до 600 |
| Пустые ответы, `stopReason=stop payloads=0` | модель слишком мелкая для агентского промпта | взять модель побольше или `compat.supportsTools: false` |

### Если железа не хватает

Полностью бесплатно и без локальной модели — Google AI Studio (Gemini), бесплатный тариф
~1500 запросов в день без карты:

```bash
openclaw onboard --auth-choice gemini-api-key
# или
export GEMINI_API_KEY="ваш-ключ"
openclaw models set google/gemini-2.5-flash
openclaw gateway restart
```

Это не open source, но полностью бесплатно и работает на любом железе. Модель при этом
меняется одной строчкой в `agents.defaults.model.primary`, всё остальное (Telegram, права,
сессии) остаётся как есть.

### Вариант через Open WebUI (если он вам всё же нужен)

Работает, но только как прокси: сзади всё равно должен стоять движок (Ollama или llama.cpp).

1. В Open WebUI: **Settings → Account → API keys** → создать ключ (`sk-...`).
2. Убедиться, что включён доступ к API (`ENABLE_API_KEY=true`, по умолчанию включён).
3. Конфиг: `configs/openclaw.openwebui.json` — там `baseUrl: "http://127.0.0.1:3000/api"`,
   а `id` модели — ровно тот, что показывает `GET /api/models`.

---

## Часть 2 — Починить старую связку на Ollama

Не угадывайте, а идите лестницей: сначала смотрим, **где** обрыв — в Ollama, в шлюзе OpenClaw
или в Telegram.

Быстрый способ пройти всю лестницу сразу:

```bash
bash openclaw/diagnose.sh          # macOS / Linux
powershell -File openclaw\diagnose.ps1   # Windows
```

Скрипт проверит Node, версию OpenClaw, статус шлюза, живость Ollama, наличие моделей,
валидность Telegram-токена и выведет вердикт по каждому пункту.

### Шаг 1. Диагностическая лестница OpenClaw

Выполнять строго в этом порядке:

```bash
openclaw status
openclaw gateway status
openclaw doctor
openclaw channels status --probe
openclaw logs --follow
```

Здоровое состояние: `Runtime: running`, `Connectivity probe: ok`, канал Telegram —
`connected`, `openclaw doctor` без блокирующих ошибок.

### Шаг 2. Если ломается после обновления (самый частый случай)

Симптомы: канал Telegram «исчез», шлюз не стартует, модель отвечает 401.

```bash
openclaw status --all
openclaw update status --json
openclaw gateway status --deep
openclaw doctor --fix
openclaw gateway restart
openclaw status --all
```

Что искать в выводе:

- `plugin load failed: dependency tree corrupted; run openclaw doctor --fix` — канал настроен,
  но плагин не загрузился. Лечит именно `doctor --fix` (чистит битые симлинки зависимостей
  плагинов и устаревшие auth-тени), затем рестарт.
- «Split brain»: два разных бинарника `openclaw` в системе, старый пытается работать с конфигом,
  который записала более новая версия. Проверка:
  ```bash
  which -a openclaw          # Windows: where openclaw
  openclaw --version
  openclaw config get meta.lastTouchedVersion
  ```
  Если `lastTouchedVersion` новее установленного бинарника — почините `PATH` и переустановите
  службу: `openclaw gateway install --force && openclaw gateway restart`.

### Шаг 3. Проверить сам Ollama

```bash
ollama --version
ollama list                     # какие модели реально скачаны
ollama ps                       # что загружено в память сейчас
curl http://127.0.0.1:11434/api/tags
```

Если `curl` не отвечает — демон не поднят:

```bash
# Linux (systemd)
systemctl status ollama
sudo systemctl restart ollama

# macOS / вручную
ollama serve

# Windows — проверьте иконку Ollama в трее, либо перезапустите службу
```

Проверить, что модель вообще генерирует:

```bash
ollama run qwen3:8b "скажи: понг"
```

Если модели нет в списке — она пропала при обновлении/чистке диска:

```bash
ollama pull qwen3:8b
```

### Шаг 4. Проверить, что OpenClaw видит Ollama

```bash
export OLLAMA_API_KEY="ollama-local"          # Windows: setx OLLAMA_API_KEY ollama-local
openclaw models list --provider ollama
openclaw models status
```

**Три самые частые ошибки в конфиге Ollama:**

1. **`/v1` в `baseUrl`.** OpenClaw ходит в **нативный** API Ollama (`/api/chat`), а не в
   OpenAI-совместимый `/v1`. Правильно:
   ```json5
   { models: { providers: { ollama: {
       baseUrl: "http://127.0.0.1:11434",   // БЕЗ /v1
       api: "ollama",                       // явно, чтобы работал нативный tool-calling
       apiKey: "ollama-local"
   } } } }
   ```
   Старые гайды советовали `baseUrl: ".../v1"` + `api: "openai-completions"` — это legacy-режим,
   и именно он чаще всего «ломается» после обновления OpenClaw.

2. **Нет `apiKey` / `OLLAMA_API_KEY`.** Для локального хоста значение любое, но оно **обязано быть**,
   иначе провайдер не включится:
   ```bash
   openclaw config set models.providers.ollama.apiKey "ollama-local"
   ```

3. **Имя модели не совпадает с `ollama list`.** `qwen3:8b` ≠ `qwen3:8b-instruct` ≠ `qwen3:latest`.
   Сверьте символ в символ и задайте:
   ```bash
   openclaw models set ollama/qwen3:8b
   ```

Готовый рабочий конфиг — `configs/openclaw.ollama.json`.

Точечная проверка модели в обход всей агентской обвязки:

```bash
OLLAMA_API_KEY=ollama-local openclaw infer model run \
  --local --model ollama/qwen3:8b --prompt "Reply with exactly: pong" --json
```

Если эта команда работает, а бот в Telegram молчит — проблема **не в модели**, а в канале
(шаг 5) или в размере агентского промпта (шаг 6).

### Шаг 5. Проверить канал Telegram

```bash
openclaw channels status --probe
openclaw pairing list telegram
openclaw config get channels
```

| Симптом | Причина | Лечение |
|---|---|---|
| `getMe returned 401` при старте | токен протух/скопирован с пробелом | перевыпустить в BotFather, обновить `channels.telegram.botToken` или `TELEGRAM_BOT_TOKEN` |
| `/start` уходит, ответа нет | ждёт подтверждения пары | `openclaw pairing approve telegram <КОД>` |
| Молчит в группе | включён privacy mode или `requireMention` | BotFather `/setprivacy` → Disable, затем удалить и заново добавить бота в группу |
| Молчит только у вас после апдейта | в allowlist остались `@username` вместо числовых ID | `openclaw doctor --fix` (резолвит их в числовые) |
| `fetch failed`, `getUpdates failed` | DNS/IPv6/прокси до `api.telegram.org` | проверить сеть; часто виноват сломанный IPv6-egress |
| `BOT_COMMANDS_TOO_MUCH` | слишком много команд от плагинов/скиллов | сократить набор или отключить нативное меню команд |

Ручная проверка токена (подставьте свой):

```bash
curl "https://api.telegram.org/bot<ВАШ_ТОКЕН>/getMe"
```

### Шаг 6. Если бот «отвечает ошибкой» или пустотой

Такое бывает, когда модель формально жива, но не тянет агентский промпт OpenClaw
(system prompt + схемы инструментов = 10k+ токенов).

```json5
{
  models: { providers: { ollama: {
    baseUrl: "http://127.0.0.1:11434",
    api: "ollama",
    apiKey: "ollama-local",
    timeoutSeconds: 300,
    models: [{
      id: "qwen3:8b",
      name: "qwen3:8b",
      reasoning: false,
      input: ["text"],
      params: { num_ctx: 32768, keep_alive: "15m" }   // контекст и «не выгружать модель»
      // при упорных падениях на инструментах:
      // compat: { supportsTools: false }
    }]
  } } }
}
```

- `num_ctx: 32768` — Ollama по умолчанию режет контекст (часто до 4096), из-за чего агент
  «теряет» промпт и молчит.
- `keep_alive: "15m"` — модель не выгружается между сообщениями, пропадают таймауты на первом ответе.
- `timeoutSeconds: 300` — запас на холодный старт крупной модели.

### Шаг 7. Финальный рестарт

```bash
openclaw doctor --fix
openclaw gateway restart
openclaw status --all
openclaw logs --follow
```

---

## Держать оба варианта одновременно

Ничто не мешает описать и llama.cpp, и Ollama, а переключаться на лету:

```json5
{
  agents: { defaults: { model: {
    primary: "llamacpp/local-model",
    fallbacks: ["ollama/qwen3:8b"]        // если основной недоступен
  } } }
}
```

В самом Telegram-чате:

```
/model ollama/qwen3:8b
/model llamacpp/local-model
```

Это же и лучший способ диагностики: если на одном провайдере бот отвечает, а на другом нет —
вопрос точно к движку, а не к OpenClaw и не к Telegram.

---

## Что лежит в этой папке

| Файл | Назначение |
|---|---|
| `configs/openclaw.llamacpp.json` | конфиг «без Ollama», движок llama.cpp + Telegram |
| `configs/openclaw.lmstudio.json` | то же, но через LM Studio (проще, GUI) |
| `configs/openclaw.openwebui.json` | вариант через Open WebUI как прокси |
| `configs/openclaw.ollama.json` | исправленный конфиг для Ollama (нативный API) |
| `configs/openclaw.hybrid.json` | оба провайдера сразу + fallback |
| `start-llama-server.sh` / `.bat` | запуск движка модели одной командой |
| `diagnose.sh` / `diagnose.ps1` | автоматическая диагностика всей цепочки |

## Полезные ссылки

- Установка и первый запуск: <https://docs.openclaw.ai/start/getting-started>
- Канал Telegram: <https://docs.openclaw.ai/channels/telegram>
- Провайдер Ollama: <https://docs.openclaw.ai/providers/ollama>
- Локальные модели и OpenAI-совместимые бэкенды: <https://docs.openclaw.ai/gateway/local-models>
- Диагностика шлюза: <https://docs.openclaw.ai/gateway/troubleshooting>
- llama.cpp server: <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
