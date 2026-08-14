# 🤖 Агент управления Timeweb Cloud

Агент подключается к панели Timeweb Cloud через официальное API
(https://api.timeweb.cloud/api/v1) и умеет:

| Возможность | Команда |
|---|---|
| 🔍 Сводка по аккаунту, токену, ресурсам | `twagent doctor` |
| 🖥️ Облачные серверы: создать / запустить / выключить / сброс пароля / логи | `twagent servers …` |
| 🗄️ Базы данных (DBaaS): кластеры, пользователи, инстансы | `twagent db …` |
| 🌐 Домены и DNS-записи (A, CNAME, TXT, …), проверка домена | `twagent domains …`, `twagent dns …` |
| 🚀 PaaS-приложения (Apps) из git-репозитория | `twagent apps …`, `twagent vcs …` |
| 🔑 SSH-ключи панели (генерация + загрузка) | `twagent ssh-keys …` |
| 📦 Деплой на VPS по SSH: статика, docker compose, git | `twagent deploy website/docker/git …` |
| 🧠 Многошаговые планы развёртывания (YAML-runbook) | `twagent run план.yaml` |

Агент работает локально (Python 3.9+) и через GitHub Actions
(workflow `.github/workflows/timeweb-agent.yml`).

---

## 1. Установка

```bash
cd heygen-integration            # корень репозитория
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r timeweb_agent/requirements.txt
```

Без виртуального окружения можно просто:

```bash
pip install requests pyyaml paramiko
```

## 2. Токен доступа

1. Откройте панель: **https://timeweb.cloud/my/api-keys** (раздел
   **API и Terraform**).
2. Создайте токен. Для управления ресурсами нужны права на
   серверы/БД/домены.
3. Запишите его в `.env` в корне репозитория:

```bash
TIMEWEB_CLOUD_TOKEN=ваш_токен_сюда
```

Файл `.env` уже в `.gitignore` и не попадёт в Git. Никогда не
коммитьте токен и не публикуйте его в открытых логах.

Проверка подключения:

```bash
python -m timeweb_agent doctor
```

## 3. Основные команды

Все команды: `python -m timeweb_agent --help`.
Полезные глобальные флаги: `--json` (машинный вывод), `--yes`
(не спрашивать подтверждений), `-v` (подробный лог).

### Серверы

```bash
# список серверов
python -m timeweb_agent servers list
python -m timeweb_agent servers list --search heygen

# тарифы и ОС
python -m timeweb_agent presets servers
python -m timeweb_agent os list

# создать сервер: Ubuntu 24.04, самый дешёвый тариф, SSH-ключ
python -m timeweb_agent servers create heygen-app-1 --os auto --preset auto --ssh-key auto --yes

# управление
python -m timeweb_agent servers reboot heygen-app-1 --yes
python -m timeweb_agent servers stop heygen-app-1 --yes
python -m timeweb_agent servers reset-password heygen-app-1 --yes
python -m timeweb_agent servers logs heygen-app-1
python -m timeweb_agent servers delete heygen-app-1 --yes
```

### Базы данных (DBaaS)

```bash
# типы СУБД и тарифы
python -m timeweb_agent db types
python -m timeweb_agent db presets

# создать кластер MySQL (пароль сгенерируется автоматически)
python -m timeweb_agent db create mydb --type mysql --yes

# пользователь и вторая база (инстанс)
python -m timeweb_agent db add-admin mydb appuser
python -m timeweb_agent db add-instance mydb staging
python -m timeweb_agent db admins mydb
python -m timeweb_agent db delete mydb --yes
```

### Домены и DNS

```bash
python -m timeweb_agent domains list
python -m timeweb_agent domains check my-new-domain.ru

# A-запись домена на IP сервера
python -m timeweb_agent dns add example.ru A 185.105.1.42
python -m timeweb_agent dns add www.example.ru CNAME example.ru
python -m timeweb_agent dns list example.ru
python -m timeweb_agent dns delete example.ru 12345 --yes
```

### Деплой сайта на VPS по SSH

SSH-доступ задаётся в `.env`:

```bash
TW_SSH_HOST=185.105.1.42        # IP сервера
TW_SSH_USER=root
TW_SSH_PASSWORD=пароль          # или TW_SSH_KEY_PATH=/путь/к/ключу
```

```bash
# статический сайт (nginx + Let's Encrypt)
python -m timeweb_agent deploy website ./site --server heygen-app-1 --domain example.ru --yes

# приложение из локальной папки через docker compose
python -m timeweb_agent deploy docker . --server heygen-app-1 --domain app.example.ru --port 8000 --yes

# приложение из git-репозитория
python -m timeweb_agent deploy git https://github.com/me/myapp.git --branch main \
    --server heygen-app-1 --domain app.example.ru --port 8000 --yes

# MySQL в docker на сервере (альтернатива DBaaS)
python -m timeweb_agent deploy mysql --server heygen-app-1 --name mydb --user app --yes

# подготовка сервера «с нуля» (пакеты, docker, nginx, fail2ban)
python -m timeweb_agent deploy provision --server heygen-app-1 --yes

# произвольная команда / загрузка файлов
python -m timeweb_agent deploy exec --server heygen-app-1 "docker ps"
python -m timeweb_agent deploy upload ./site /var/www/example.ru
```

### PaaS-приложения (Apps) — деплой из git без своего сервера

```bash
# подключить GitHub (нужен fine-grained PAT с доступом к репозиториям)
python -m timeweb_agent vcs connect --provider github --token ghp_... --yes
python -m timeweb_agent vcs list
python -m timeweb_agent vcs repos 1
python -m timeweb_agent vcs branches 1 12345

# создать приложение из репозитория
python -m timeweb_agent apps create my-app --type backend \
    --provider-id 1 --repository-id 12345 --branch main \
    --framework-id 1 --yes

python -m timeweb_agent apps deploy my-app
python -m timeweb_agent apps logs my-app
python -m timeweb_agent apps bind-domain my-app app.example.ru
```

## 4. Планы развёртывания (runbook)

YAML-план описывает все шаги — агент выполняет их по очереди.
Примеры лежат в `timeweb_agent/examples/`:

```bash
python -m timeweb_agent run timeweb_agent/examples/deploy-website.yaml --yes
python -m timeweb_agent run timeweb_agent/examples/deploy-heygen.yaml --dry-run
```

Действия плана: `servers.create/list/wait/reboot/stop/start/delete`,
`db.create/add-admin/add-instance/delete`, `dns.add/delete`,
`domains.check/add`, `apps.create/deploy`, `sshkeys.ensure`,
`deploy.provision/website/docker/git/mysql`, `ssh.exec`, `sleep`, `echo`.

Значения подставляются через `{{ vars.X }}`, `{{ имя_шага.поле }}`,
`{{ env.NAME }}`. Результаты шагов сохраняются через `save:`.

## 5. Запуск через GitHub Actions

Если агент нужно запускать без локального окружения:

1. Добавьте секреты репозитория (Settings → Secrets and variables →
   Actions): `TIMEWEB_CLOUD_TOKEN`, при необходимости
   `TW_SSH_HOST`, `TW_SSH_USER`, `TW_SSH_PASSWORD` или `TW_SSH_KEY`.
2. Actions → **Timeweb Agent** → Run workflow → команда и аргументы.

Или через GH CLI:

```bash
gh workflow run timeweb-agent.yml -f command="doctor"
gh workflow run timeweb-agent.yml -f command="run" \
   -f args="timeweb_agent/examples/deploy-website.yaml --yes"
```

## 6. Безопасность

- Токен и пароли хранятся только в `.env` (вне Git) или в секретах
  GitHub Actions; в логах они маскируются (ключ `--show-secrets`
  отключает маскировку — не используйте в CI).
- Платные и разрушающие операции (создание сервера/БД, удаление)
  требуют явного подтверждения или флага `--yes`.
- Статусы ресурсов после создания могут ещё быть переходными —
  команды с `--wait` (по умолчанию при создании) ждут готовности.
