# 01 · Архитектура ClawDesk

## 1. Принципы

1. **OpenClaw Gateway — единственный источник правды** по сессиям, каналам и запускам агентов.
   ClawDesk ничего не дублирует: не хранит свою копию транскриптов, не роутит сообщения мимо gateway.
2. **Продуктовый слой — сбоку, а не внутри.** Всё, что можно сделать плагином, скиллом или
   конфигом OpenClaw, делается ими. Форк ядра — крайняя мера (иначе умрём на апстриме).
3. **Один бот = один контейнер = один браузерный профиль = один набор секретов.**
   Это наша заявленная граница безопасности, и её нельзя нарушать ради удобства.
4. **Действие с последствиями требует подписи.** Список необратимых операций задаётся политикой,
   а не решается моделью.
5. **Всё воспроизводимо.** Любой шаг бота имеет запись: что нажал, что увидел, что получил.

## 2. Слои

```
┌───────────────────────────────────────────────────────────────────┐
│ КЛИЕНТЫ                                                            │
│  ClawDesk Desktop (Tauri) · Web · iOS/Android node · Telegram      │
└───────────────┬───────────────────────────────────────────────────┘
                │ WSS (gateway protocol) + REST (BFF)
┌───────────────▼───────────────────────────────────────────────────┐
│ CLAWDESK BFF  (Node/TS, наш код)                                   │
│  Auth/SSO · Реестр ботов · Оркестратор задач · Очередь аппрувов    │
│  Аудит и артефакты · Биллинг/бюджеты · Trainer (обучение задач)    │
└───────────────┬───────────────────────────────────────────────────┘
                │ WS-клиент gateway protocol + CLI + hooks
┌───────────────▼───────────────────────────────────────────────────┐
│ OPENCLAW GATEWAY  (апстрим, не форкаем)                            │
│  Каналы · Сессии · Роутинг bindings · Агент-рантайм · Tools        │
│  Skills · Cron/Hooks · Sub-агенты · Tasks ledger · Sandbox         │
└───────────────┬───────────────────────────────────────────────────┘
                │ docker / podman
┌───────────────▼───────────────────────────────────────────────────┐
│ ИСПОЛНИТЕЛЬНАЯ СРЕДА                                               │
│  bot-alice: контейнер + Chrome-профиль + FS + secrets              │
│  bot-boris: контейнер + Chrome-профиль + FS + secrets              │
│  общий: объектное хранилище артефактов, Postgres, Redis            │
└───────────────────────────────────────────────────────────────────┘
```

Что берём из OpenClaw как есть:

| Потребность ClawDesk | Механизм OpenClaw |
|---|---|
| Боты как отдельные «личности» | `agents.entries.*` (workspace, model, tools, sandbox, identity) |
| Маршрутизация чат → бот | `bindings[].match` (channel/accountId/peer), детерминированно, most-specific wins |
| Тред = задача | сессии `agent:<id>:<key>`, thread-bound сессии |
| Параллельная работа | `sessions_spawn` (sub-агенты, lane `subagent`, push-completion) |
| Переписка ботов | `tools.agentToAgent` + `agents_list` + `sessions_send` |
| Умение = процедура | Skills (`SKILL.md`) + Skill Workshop (очередь предложений) |
| Расписание и триггеры | `cron.*` + `hooks.*` (входящие вебхуки с шаблонами сессий) |
| Учёт фоновой работы | Tasks ledger (`queued → running → terminal`, `openclaw tasks ...`) |
| Изоляция | `sandbox.mode` + `sandbox.scope: "agent"` + docker |
| Работа в залогиненных UI | `browser` tool, профиль `openclaw`, ручной первичный вход |
| Секреты | SecretRef / secrets management, без попадания в контекст |
| Модели и отказоустойчивость | `models.providers` + `auth.order` (failover) |

Что пишем сами (это и есть продукт):

1. **Messenger UI** — форк WebChat, доведённый до мессенджера: список ботов, треды-задачи,
   групповые чаты, инлайновые аппрувы, «показать работу», присутствие.
2. **Bot Registry & Provisioner** — CRUD ботов в терминах продукта («нанять сотрудника»),
   генерация `agents.entries` + `bindings` + `IDENTITY.md` + профиля инструментов,
   создание контейнера и браузерного профиля, отзыв доступов при увольнении.
3. **Approval Gateway** — перехват необратимых действий, карточка аппрува, TTL, эскалация,
   политика авто-аппрува по лимитам.
4. **Task Orchestrator** — продуктовая обёртка над tasks/subagents: SLA, ретраи, зависимости,
   бюджеты, ежедневная сводка.
5. **Routine Trainer** — «покажи один раз»: запись демонстрации → черновик `SKILL.md` →
   верификационный прогон → публикация и расписание.
6. **Audit & Evidence** — все действия браузера/шелла со скриншотами и диффами,
   неизменяемый лог, экспорт.
7. **Cost & Budget** — токены и деньги по боту/задаче/команде, лимиты и hard-stop.

## 3. Компоненты BFF

Стек: TypeScript, Node 26, Fastify, Postgres 16 (Drizzle), Redis, S3-совместимое хранилище,
BullMQ на очередях, Zod/TypeBox на схемах.

```
apps/
  desktop/            Tauri-обёртка (macOS/Win/Linux)
  web/                Messenger UI (React + Vite, WS-клиент)
  bff/                Fastify API + WS-мост + воркеры
packages/
  gateway-client/     типизированный клиент gateway protocol (WS)
  bot-spec/           схема бота: роль, инструменты, доступы, политика
  routine-spec/       схема рутины и её компиляция в SKILL.md
  policy/             движок политик аппрувов и DLP
  ui-kit/             компоненты мессенджера
plugins/
  clawdesk-bridge/    OpenClaw-плагин: хуки on-tool-call, on-run-end
  clawdesk-recorder/  запись демонстраций и трасс браузера
skills/
  clawdesk-core/      базовые скиллы: self-check, отчёт в тред, запрос аппрува
infra/
  docker-compose.yml  локальный стек
  helm/               VPC-развёртывание
```

### 3.1 Bot Registry & Provisioner

Продуктовая сущность «бот» → набор артефактов OpenClaw:

```
BotSpec {
  id, displayName, avatar, role,
  persona: { tone, language, workingHours, timezone },
  model: { primary, fallback, thinking, budgetPerTaskUsd },
  toolProfile: "reader" | "operator" | "engineer" | custom,
  accesses: [ { service, method: "browser-login"|"api-key"|"oauth", secretRef } ],
  sandbox: { image, cpu, memory, idleFreezeMinutes },
  approvals: { policyId },
  routines: [ routineId ],
  channels: [ { channel, accountId, peer } ]
}
```

Provisioner при создании бота:

1. Пишет `agents.entries.<botId>` и `bindings[]` в `openclaw.json` (через API конфига gateway,
   с валидацией и hot-reload; конфиг версионируем в git-репозитории состояния).
2. Создаёт workspace `~/.clawdesk/workspaces/<botId>` с `IDENTITY.md`, `AGENTS.md`, `GOALS.md`.
3. Поднимает docker-контейнер `clawdesk/bot-runtime:<ver>` с меткой `clawdesk.bot=<botId>`,
   монтирует workspace и `chrome-profile/<botId>`.
4. Кладёт секреты в vault и выдаёт только SecretRef.
5. Регистрирует в БД, отдаёт UI карточку «сотрудник нанят».

Профили инструментов (перевод BotSpec → `tools.allow/deny`):

| Профиль | allow | deny | sandbox |
|---|---|---|---|
| `reader` | `read`, `web`, `browser(readonly)`, `sessions_history` | `exec`, `write`, `edit`, `cron`, `nodes` | `all`, scope agent |
| `operator` | + `browser(full)`, `write`, `message`, `sessions_spawn` | `exec`, `apply_patch` | `all`, scope agent |
| `engineer` | + `exec`, `apply_patch`, `cron` | `nodes` | `all`, scope agent, elevated только по аппруву |
| `dispatcher` | `agents_list`, `sessions_spawn`, `sessions_send`, `sessions_yield` | всё остальное | `all` |

### 3.2 Task Orchestrator

Жизненный цикл задачи в терминах продукта:

```
draft → planned → running → needs_approval → running → verifying → done
                        └→ blocked (нужен человек)   └→ failed → retry(n)
```

Правила, закрывающие «90 vs 100»:

- **Обязательный шаг verifying.** Перед `done` бот выполняет проверку результата
  независимым способом (перечитать созданную запись через API/UI, сверить сумму, открыть URL).
  Отчёт «готово» без артефакта проверки не принимается — оркестратор возвращает задачу в работу.
- **Definition of Done в самой задаче.** При постановке задачи Trainer/бот формулирует
  критерии приёмки списком; они хранятся в задаче и проверяются на шаге verifying.
- **Ретраи с разбором.** Провал → бот пишет причину, меняет подход, максимум N=3,
  дальше `blocked` с человеко-читаемым вопросом.
- **Бюджет.** Достигнут лимит токенов/времени → `blocked`, а не тихое «сделал что смог».
- **Никакого polling.** Ожидание результата sub-агента строится на `sessions_yield`
  и push-completion, как требует OpenClaw.

Декомпозиция: задача = дерево. Корень в треде пользователя, дети — `sessions_spawn`
с `context: "isolated"` по умолчанию и `fork` только когда нужен контекст диалога.

### 3.3 Approval Gateway

Перехват на уровне плагина `clawdesk-bridge` через хук на вызов инструмента:

```
on_tool_call(botId, tool, args) →
   policy.evaluate(botId, tool, args) →
      allow                    → пропускаем
      allow_with_receipt       → пропускаем, пишем в аудит как значимое
      require_approval(reason) → создаём Approval, приостанавливаем шаг,
                                 шлём карточку в тред, ждём TTL
      deny(reason)             → возвращаем модели отказ с объяснением
```

Что требует подписи по умолчанию (конфигурируемо):

- любой платёж, перевод, изменение реквизитов;
- отправка письма/сообщения вовне организации;
- удаление данных, массовое изменение записей (> N строк);
- изменение прав доступа, приглашение пользователей;
- публикация публичного контента;
- покупка/подписка;
- любое действие в сервисе, помеченном как `critical`;
- `exec` вне sandbox (elevated).

Карточка аппрува содержит: что бот собирается сделать, на каком основании, скриншот
текущего экрана, дифф/сумму, оценку необратимости, кнопки **Одобрить / Изменить / Отклонить**
и опцию **«Больше не спрашивать для этого типа до $X»** (создаёт правило авто-аппрува
с лимитом и сроком действия).

TTL по умолчанию 24 ч; истёк — задача `blocked`, бот не действует. Тихого прохода нет.

### 3.4 Routine Trainer («покажи один раз»)

Три способа обучить бота, по возрастанию точности:

1. **Рассказать.** Пользователь пишет процедуру текстом → LLM превращает в черновик
   `SKILL.md` → тестовый прогон → правки.
2. **Показать (основной).** Пользователь жмёт «Обучить» → открывается браузерное окно
   с recorder-расширением → человек делает работу руками → recorder пишет трассу:
   URL, роли и селекторы элементов, вводимый текст (с маскированием секретов), скриншоты.
   → Компилятор строит `RoutineSpec` (шаги, параметры, точки принятия решений, критерии
   успеха) → генерирует `SKILL.md` + опциональный детерминированный Playwright-скрипт
   для устойчивых шагов → бот делает пробный прогон на тестовых данных под наблюдением
   → пользователь подтверждает → скилл публикуется через Skill Workshop.
3. **Подсмотреть.** Бот сам замечает повторяющуюся работу в тредах и предлагает
   оформить её рутиной (Skill Workshop как раз для этого и сделан).

`RoutineSpec` (см. `examples/routine.schema.json`):

```
Routine {
  id, name, description,
  trigger: { type: "manual"|"cron"|"webhook"|"watch", spec },
  inputs: [ { name, type, required, source } ],
  steps: [ { kind: "browser"|"api"|"llm"|"human", instruction, selectorHints,
             evidence: "screenshot"|"dom"|"none", onFail: "retry"|"ask"|"abort" } ],
  approvals: [ stepId ],
  acceptance: [ "текстовые критерии приёмки" ],
  outputs: [ { name, type } ]
}
```

Компиляция: `RoutineSpec` → `SKILL.md` (frontmatter + тело с процедурой) кладётся
в `<workspace>/skills/<routine-id>/SKILL.md`. Скилл виден только своему боту
(per-agent skills) или добавляется в общий пул через allowlist.

**Гибридное исполнение** — важная деталь надёжности: устойчивые шаги (логин, навигация,
табличный экспорт) исполняются детерминированным скриптом; шаги, требующие суждения
(выбрать нужную строку, сформулировать ответ) — моделью. Это резко снижает и стоимость,
и флаки.

### 3.5 Audit & Evidence

Каждое действие пишется как событие:

```
Event { id, ts, botId, taskId, stepId, kind, tool, argsRedacted,
        result: "ok"|"error", evidenceRefs[], costTokens, durationMs }
```

Скриншоты браузера — до и после каждого значимого клика, WebP, 90 дней (настраивается).
Файловые операции — дифф. Шелл — команда и вывод с редакцией секретов.
Лог неизменяемый (append-only + hash-chain), экспорт в JSONL/CSV для комплаенса.

В UI это превращается в кнопку «Показать работу» — таймлайн скриншотов с подписями шагов.
Это одновременно и доверие, и главный инструмент отладки рутин.

### 3.6 Cost & Budget

- Токены забираем из usage-метрик gateway, конвертим в деньги по прайсу провайдера.
- Бюджеты: на задачу, на бота в день, на команду в месяц. Достижение → `blocked` + уведомление.
- В треде у каждой задачи видно: время, шаги, токены, деньги.
- Дефолтная модель — дешёвая; эскалация на дорогую по правилу (сложность/провал/явный запрос).

## 4. Изоляция и безопасность

Это место, где мы обязаны быть строже конкурента, потому что именно это и продаём.

**Уровни изоляции:**

| Уровень | Механизм |
|---|---|
| Процесс/ФС | отдельный docker-контейнер на бота (`sandbox.scope: "agent"`), read-only корень, tmpfs, свой uid |
| Сеть | egress-allowlist на бота (только домены его сервисов), запрет доступа к метаданным облака и к RFC1918 |
| Браузер | отдельный Chrome-профиль и отдельный CDP-порт на бота, cookies не пересекаются |
| Секреты | vault + SecretRef, инъекция на уровне рантайма, никогда не в контекст модели, редакция в логах |
| Контекст | сессии изолированы; sub-агенты `isolated` по умолчанию; agent-to-agent только по allowlist |
| Данные | per-bot workspace, общий доступ только через явно расшаренные артефакты |

**Модель угроз (кратко):**

| Угроза | Контроль |
|---|---|
| Prompt injection со страницы/письма | Недоверенный контент обрабатывает бот с профилем `reader` и без секретов; результат передаётся операционному боту как данные, а не как инструкции; необратимое — только через аппрув |
| Утечка секрета в ответ модели | Секреты не попадают в контекст; выходной фильтр на паттерны ключей; редакция в аудите |
| Захват сессии браузера | Профиль в шифрованном томе; блокировка экспорта cookies; ротация по расписанию |
| Побег из sandbox | Нет docker.sock внутрь, seccomp/apparmor, без privileged, лимиты cgroup |
| Злоупотребление agent-to-agent | Выключено по умолчанию; allowlist пар; лимит глубины вложенности; квота сообщений |
| Инсайдер | RBAC, неизменяемый аудит, требование двух подписей для `critical`-сервисов |
| Блокировка аккаунта сервисом | Ручной первичный логин, человеческий темп, детект капчи → эскалация, приоритет API |

**Аутентификация людей:** локально — device pairing gateway; в команде — OIDC (Keycloak/Okta/
Google Workspace), RBAC роли `owner / admin / operator / viewer`.

**Данные:** шифрование на диске (LUKS/EBS), в транзите TLS, артефакты в S3 с SSE и
пресайнед-ссылками на 15 мин.

## 5. Схема данных (Postgres, основное)

```sql
orgs(id, name, plan, created_at)
users(id, org_id, email, role, sso_subject)
bots(id, org_id, slug, display_name, role, spec_json, state, agent_id, created_at)
bot_accesses(id, bot_id, service, method, secret_ref, status, last_login_at, health)
threads(id, org_id, kind /* dm|group|task */, title, bot_ids[], session_key, created_at)
tasks(id, thread_id, bot_id, parent_task_id, title, definition_of_done jsonb,
      status, budget_usd, spent_usd, tokens, started_at, finished_at, oc_task_id)
task_steps(id, task_id, idx, kind, instruction, status, evidence_ref, error)
approvals(id, task_id, step_id, bot_id, kind, payload jsonb, risk, status,
          requested_at, decided_at, decided_by, ttl_at, auto_rule_id)
approval_rules(id, org_id, bot_id, matcher jsonb, limit_usd, expires_at, created_by)
routines(id, org_id, bot_id, name, spec_json, skill_path, version, status, trigger jsonb)
routine_runs(id, routine_id, task_id, status, started_at, finished_at)
events(id, org_id, bot_id, task_id, ts, kind, tool, args_redacted jsonb,
       result, cost_tokens, duration_ms, prev_hash, hash)
artifacts(id, org_id, task_id, kind, s3_key, mime, bytes, created_at)
budgets(id, org_id, scope /* org|bot|task */, ref_id, period, limit_usd, spent_usd)
```

Транскрипты диалогов **не дублируем** — они живут в session store OpenClaw;
в БД только ключи сессий и метаданные.

## 6. Ключевые потоки

### 6.1 Постановка задачи

```
Пользователь пишет в чат бота
  → BFF принимает WS-сообщение, создаёт task(draft)
  → отправляет в gateway: agent run (session = thread session key)
  → бот отвечает планом + Definition of Done → task(planned)
  → пользователь подтверждает (или бот стартует сразу, если рутина известна)
  → бот выполняет шаги, каждый значимый шаг → event + evidence
  → на необратимом шаге → Approval → пауза
  → пользователь одобряет → продолжение
  → шаг verifying: бот независимо проверяет результат
  → task(done) + отчёт в тред + стоимость
```

### 6.2 Обучение рутины

```
«Обучить Алису выгружать отчёт из банка»
  → Trainer открывает окно записи (Chrome-профиль бота)
  → человек делает всё руками; recorder пишет трассу + скриншоты
  → «Готово» → компилятор строит RoutineSpec, спрашивает про параметры
    («сумма и период меняются?») и критерии успеха
  → генерируется SKILL.md + playwright-скрипт устойчивых шагов
  → пробный прогон в тестовом режиме, дифф ожидаемого/полученного
  → публикация через Skill Workshop, назначение расписания
```

### 6.3 Групповая задача

```
Пользователь в #запуск-лендинга: «@Гоша ресёрч конкурентов, @Вера тексты, @Борис проверь юр.»
  → Dispatcher создаёт корневую задачу и три дочерних (sessions_spawn, isolated)
  → каждый бот работает в своём треде, статус виден в корневом
  → результаты приходят push-completion в корневую сессию
  → диспетчер синтезирует итог, задаёт вопросы, где противоречия
  → один отчёт пользователю
```

## 7. Развёртывание

**Локально (dev/solo):** `docker compose up` — gateway, postgres, redis, minio, bff, web.
Боты — контейнеры, создаются на лету.

**Команда (self-host):** одна VM (8 vCPU / 32 ГБ хватает на ~10 активных ботов),
traefik + TLS, tailnet для доступа, бэкапы Postgres и workspace.

**VPC/Enterprise:** Helm-чарт, боты — поды с ResourceQuota, NetworkPolicy на egress-allowlist,
секреты в облачном KMS, логи в SIEM клиента.

**Idle-freeze:** контейнер бота без активности 10 минут паузится (`docker pause` /
scale-to-zero), браузерный профиль и workspace сохраняются на томе. Просыпание < 3 с.
Именно это делает $29 возможными.

## 8. Что осознанно не делаем в v1

- Свою модель и свой инференс.
- Android-приложение (используем OpenClaw Android node).
- Полноценный маркетплейс с монетизацией (сначала просто каталог шаблонов).
- Голосовой интерфейс (есть в OpenClaw, включим позже).
- Мультитенантный SaaS с нашим хостингом инференса — только self-host и managed VPC.
