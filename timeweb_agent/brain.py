"""Интеллектуальный слой агента.

Запрос на естественном языке («Создай на сервере сайт для клиента Maria,
PostgreSQL, Redis, Nginx и HTTPS на домене maria.ru») превращается в план
действий, который выполняется, проверяется и описывается в отчёте.

Источники интеллекта (по приоритету):
  1. LLM (настройки TW_AI_* в .env):
     - Timeweb Cloud AI — агент из панели (оплата в рублях с аккаунта),
       TW_AI_AGENT_ID=идентификатор агента;
     - OpenAI-совместимый API: TW_AI_URL + TW_AI_TOKEN + TW_AI_MODEL
       (OpenAI, OpenRouter, локальный Ollama и т.д.).
  2. Встроенный анализатор правил (русский язык) — работает вообще
     без ключей: сайты, серверы, БД, DNS, HTTPS, диагностика.

Пайплайн: понять → спланировать → подтвердить → выполнить →
проверить каждый шаг → отчёт.
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Any, Optional

import requests

from . import api, config, runbook, verify
from .client import TimewebClient
from .ssh import SSHError

# ---------------------------------------------------------------------- #
#  Описание действий для LLM
# ---------------------------------------------------------------------- #
ACTIONS_SPEC: dict[str, dict] = {
    "servers.create": {
        "описание": "Создать облачный сервер (если с таким именем уже есть — вернёт существующий, ничего не закажет).",
        "params": {
            "name": "имя сервера (латиница, можно с дефисом)",
            "os": "'auto' или ID ОС",
            "preset": "'auto' или ID тарифа",
            "ssh_key": "'auto' — сгенерировать SSH-ключ автоматически",
            "wait": "true — дождаться готовности",
        },
        "save": "server",
        "verify": "нет",
    },
    "dns.add": {
        "описание": "Добавить DNS-запись домена (A, CNAME, TXT, MX...) в панели Timeweb.",
        "params": {
            "fqdn": "домен или поддомен, напр. example.ru или www.example.ru",
            "type": "A | AAAA | CNAME | TXT | MX | NS | SRV | CAA",
            "value": "значение записи (IP для A, имя хоста для CNAME)",
            "ttl": "TTL в секундах (3600)",
        },
        "save": "dns_rec",
        "verify": "нет",
    },
    "domains.check": {
        "описание": "Проверить, свободен ли домен для регистрации.",
        "params": {"fqdn": "домен"},
        "save": "нет",
        "verify": "нет",
    },
    "domains.add": {
        "описание": "Добавить (зарегистрировать) домен на аккаунт — платно.",
        "params": {"fqdn": "домен"},
        "save": "нет",
        "verify": "нет",
    },
    "deploy.provision": {
        "описание": "Подготовить сервер: обновить пакеты, установить docker, nginx, fail2ban.",
        "params": {"server": "имя сервера из панели", "docker": "true"},
        "save": "нет",
        "verify": {"kind": "nginx", "params": {}},
    },
    "deploy.website": {
        "описание": "Развернуть статический сайт: nginx + Let's Encrypt (HTTPS). Если папки/файлов нет — создаст страницу-заглушку.",
        "params": {
            "server": "имя сервера из панели",
            "domain": "домен сайта",
            "ssl": "true — выпустить HTTPS-сертификат",
            "path": "локальная папка с сайтом (необязательно)",
            "title": "заголовок страницы-заглушки (необязательно)",
        },
        "save": "site",
        "verify": {"kind": "http", "params": {"url": "https://{{ domain }}", "expect": 200}},
    },
    "deploy.docker": {
        "описание": "Развернуть приложение из локальной папки с docker-compose.yml + nginx-прокси + HTTPS.",
        "params": {
            "server": "имя сервера", "path": "папка с docker-compose.yml",
            "domain": "домен", "port": "порт приложения", "ssl": "true",
        },
        "save": "нет",
        "verify": {"kind": "http", "params": {"url": "https://{{ domain }}"}},
    },
    "deploy.git": {
        "описание": "Клонировать приложение из git-репозитория на сервер и запустить через docker compose (с nginx+HTTPS, если указан домен).",
        "params": {
            "server": "имя сервера", "repo": "URL репозитория", "branch": "ветка",
            "domain": "домен (необязательно)", "port": "порт", "ssl": "true",
        },
        "save": "нет",
        "verify": "нет",
    },
    "deploy.mysql": {
        "описание": "Запустить MySQL в docker-контейнере на сервере (данные на постоянном томе).",
        "params": {"server": "имя сервера", "name": "имя базы", "user": "пользователь"},
        "save": "mysql",
        "verify": {"kind": "mysql", "params": {
            "container": "{{ mysql.container }}", "user": "{{ mysql.user }}",
            "password": "{{ mysql.password }}", "database": "{{ mysql.database }}"}},
    },
    "deploy.postgres": {
        "описание": "Запустить PostgreSQL в docker-контейнере на сервере.",
        "params": {"server": "имя сервера", "name": "имя базы", "user": "пользователь"},
        "save": "postgres",
        "verify": {"kind": "postgres", "params": {
            "container": "{{ postgres.container }}", "user": "{{ postgres.user }}",
            "password": "{{ postgres.password }}", "database": "{{ postgres.database }}"}},
    },
    "deploy.redis": {
        "описание": "Запустить Redis в docker-контейнере на сервере (с паролем).",
        "params": {"server": "имя сервера", "name": "имя инстанса"},
        "save": "redis",
        "verify": {"kind": "redis", "params": {
            "container": "{{ redis.container }}", "password": "{{ redis.password }}"}},
    },
    "db.create": {
        "описание": "Создать управляемый кластер БД Timeweb (DBaaS) — не на сервере, а в облаке.",
        "params": {
            "name": "имя кластера", "type": "mysql | postgresql | redis | mongodb",
            "admin_login": "логин админа", "wait": "true",
        },
        "save": "database",
        "verify": "нет",
    },
    "db.add-admin": {
        "описание": "Создать пользователя в кластере БД.",
        "params": {"db": "имя или ID кластера", "login": "логин"},
        "save": "нет",
        "verify": "нет",
    },
    "db.add-instance": {
        "описание": "Создать базу (инстанс) внутри кластера БД.",
        "params": {"db": "имя или ID кластера", "name": "имя базы"},
        "save": "нет",
        "verify": "нет",
    },
    "ssh.exec": {
        "описание": "Выполнить произвольную команду на сервере по SSH.",
        "params": {"server": "имя сервера", "command": "команда"},
        "save": "нет",
        "verify": "нет",
    },
    "check": {
        "описание": "Проверить результат. kind: http | dns | command | docker | postgres | mysql | redis | nginx.",
        "params": {"kind": "вид проверки", "server": "имя сервера (кроме http/dns)", "url": "для http", "domain": "для dns", "command": "для command", "name": "имя контейнера (docker)", "container/user/password/database": "для postgres/mysql/redis"},
        "save": "нет",
        "verify": "нет",
    },
}

# Переменные подстановки, которые агент умеет подставлять в шаблоны
SUBSTITUTIONS_HELP = (
    "Значения подставляются из сохранённых результатов шагов: {{ server.ip }}, "
    "{{ server.name }}, {{ postgres.password }}, {{ redis.container }} и т.п. "
    "Сохраняйте результаты через save: {\"as\": \"имя\"}."
)


def actions_schema_text() -> str:
    lines = []
    for name, spec in ACTIONS_SPEC.items():
        lines.append(f"- {name}: {spec['описание']}")
        for pname, pdesc in spec.get("params", {}).items():
            lines.append(f"    with.{pname}: {pdesc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- #
#  LLM-клиент (OpenAI-совместимый)
# ---------------------------------------------------------------------- #
class LLMError(RuntimeError):
    pass


class LLM:
    """Клиент OpenAI-совместимого chat completions.

    Провайдеры:
      - timeweb: агент из панели Timeweb Cloud AI (TW_AI_AGENT_ID),
        токен — TIMEWEB_CLOUD_TOKEN или TW_AI_TOKEN;
      - openai/custom: TW_AI_URL + TW_AI_TOKEN + TW_AI_MODEL.
    """

    def __init__(self, provider: Optional[str] = None):
        provider = (provider or config.get("TW_AI_PROVIDER") or "").strip().lower()
        agent_id = config.get("TW_AI_AGENT_ID")
        url = config.get("TW_AI_URL")
        token = config.get("TW_AI_TOKEN") or config.API_TOKEN
        model = config.get("TW_AI_MODEL")

        if provider in {"", "auto"}:
            if agent_id:
                provider = "timeweb"
            elif url:
                provider = "custom"
            elif config.get("TW_AI_TOKEN"):
                provider = "openai"
            else:
                raise LLMError("LLM не настроен")

        if provider == "timeweb":
            if not agent_id:
                raise LLMError("Для Timeweb Cloud AI задайте TW_AI_AGENT_ID в .env")
            self.url = (
                f"https://agent.timeweb.cloud/api/v1/cloud-ai/agents/{agent_id}"
                f"/v1/chat/completions"
            )
            self.token = config.get("TW_AI_TOKEN") or config.API_TOKEN
            self.model = model or "auto"
        elif provider == "openai":
            self.url = (url or "https://api.openai.com/v1") + "/chat/completions"
            self.token = token
            self.model = model or "gpt-4o-mini"
        else:  # custom
            if not url:
                raise LLMError("Для кастомного LLM задайте TW_AI_URL в .env")
            self.url = url.rstrip("/")
            if not self.url.endswith("/chat/completions"):
                self.url += "/chat/completions"
            self.token = token
            self.model = model or "auto"
        if not self.token:
            raise LLMError("Нет токена для LLM (TW_AI_TOKEN или TIMEWEB_CLOUD_TOKEN)")
        self.provider = provider

    def chat(self, messages: list, temperature: float = 0.2, json_mode: bool = True) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = requests.post(
            self.url,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json=payload,
            timeout=int(config.get("TW_AI_TIMEOUT", "180") or 180),
        )
        if resp.status_code != 200:
            hint = ""
            if resp.status_code in {400, 404, 422}:
                hint = (
                    " Проверьте TW_AI_MODEL (список моделей агента можно получить в панели "
                    "Timeweb Cloud AI) и TW_AI_URL."
                )
            raise LLMError(f"LLM ответил {resp.status_code}: {resp.text[:400]}{hint}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Неожиданный формат ответа LLM: {str(data)[:300]}") from e


def get_llm() -> Optional[LLM]:
    """Возвращает настроенный LLM или None (тогда работает анализатор правил)."""
    try:
        return LLM()
    except LLMError:
        return None


# ---------------------------------------------------------------------- #
#  Валидация плана
# ---------------------------------------------------------------------- #
def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise runbook.RunbookError("План должен быть объектом JSON")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise runbook.RunbookError("В плане нет шагов (steps)")
    for s in steps:
        if not isinstance(s, dict):
            raise runbook.RunbookError("Каждый шаг плана должен быть объектом")
        action = s.get("action")
        if action not in runbook.ACTIONS:
            raise runbook.RunbookError(f"Неизвестное действие в плане: {action}")
        if not isinstance(s.get("with", {}), dict):
            raise runbook.RunbookError(f"Шаг {action}: with должен быть объектом")
        if "verify" in s and s["verify"] is not None and not isinstance(s["verify"], dict):
            raise runbook.RunbookError(f"Шаг {action}: verify должен быть объектом")
    return plan


# ---------------------------------------------------------------------- #
#  Планирование через LLM
# ---------------------------------------------------------------------- #
SYSTEM_PROMPT = """Ты — планировщик операций агента управления облаком Timeweb Cloud и Linux-серверами.
Пользователь пишет запрос на естественном языке (обычно по-русски), а ты составляешь из него
ПОШАГОВЫЙ ПЛАН действий и отвечаешь ТОЛЬКО корректным JSON без пояснений.

Формат ответа:
{"summary": "краткое описание плана по-русски", "steps": [
  {"action": "имя действия из списка", "name": "описание шага по-русски",
   "with": {"параметры действия"}, "save": {"as": "имя"} (если результат нужен дальше),
   "verify": {"kind": "http|dns|command|docker|postgres|mysql|redis|nginx", "params": {...}} (если применимо)}
]}

ДОСТУПНЫЕ ДЕЙСТВИЯ (только эти, не выдумывай другие):
{actions}

ПРАВИЛА:
1. Используй только действия из списка выше, с правильными именами параметров.
2. {subst}
3. Если запрос про «новый сайт» без файлов — используй deploy.website с параметром
   title (страница-заглушка) и ssl: true. Сервер перед этим подготовь через deploy.provision.
4. Если запрос про «PostgreSQL/Redis/MySQL на сервере» — используй deploy.postgres /
   deploy.redis / deploy.mysql (docker на VPS). «Управляемая/облачная база» — db.create.
5. Домен перед деплоем привязывай A-записью (dns.add) на IP сервера, www — CNAME.
6. Для каждого действия с побочным эффектом (сайт, БД, контейнер) добавь verify,
   используя подстановки из save. http-проверки — с expect 200.
7. Не создавай сервер, если он уже есть или запрос про «мой/существующий сервер».
8. План должен быть минимальным, но полным: никаких лишних шагов.

КОНТЕКСТ АККАУНТА:
{context}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ: {request}"""


def _context_text(client: TimewebClient) -> str:
    lines = []
    try:
        servers = api.list_servers(client)
        lines.append(
            "Серверы: "
            + (", ".join(f"{s.get('name')} (ip={api.server_ip(s) or '?'}, status={s.get('status')})" for s in servers) or "нет")
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        domains = api.list_domains(client)
        lines.append("Домены: " + (", ".join(d.get("fqdn", "") for d in domains) or "нет"))
    except Exception:  # noqa: BLE001
        pass
    if config.SSH_HOST:
        lines.append(f"SSH-доступ из .env: {config.SSH_HOST}")
    return "\n".join(lines)


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"LLM не вернул JSON: {text[:300]}")
    return json.loads(text[start : end + 1])


def llm_plan(llm: LLM, request_text: str, client: TimewebClient) -> dict:
    prompt = SYSTEM_PROMPT.format(
        actions=actions_schema_text(),
        subst=SUBSTITUTIONS_HELP,
        context=_context_text(client),
        request=request_text,
    )
    raw = llm.chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": request_text},
        ],
        temperature=0.1,
        json_mode=True,
    )
    plan = _extract_json(raw)
    return validate_plan(plan)


# ---------------------------------------------------------------------- #
#  Встроенный анализатор правил (без LLM)
# ---------------------------------------------------------------------- #
_DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9-]*\.(?:[a-z]{2,10}|рф|рус|онлайн|сайт))\b", re.I)
_CLIENT_RE = re.compile(r"(?:для\s+)?(?:клиента|проекта)\s+([A-ZА-ЯЁ][a-zа-яё-]+)", re.I)
_SERVER_RE = re.compile(r"(?:на|в)\s+(?:мо[её]м\s+)?сервере\s+([A-Za-z0-9_-]+)", re.I)
_NEW_SERVER_RE = re.compile(r"нов(?:ый|ого|ому|ым)\s+сервер|создай\s+сервер|подними\s+сервер|закажи\s+сервер", re.I)
_SERVER_STOPWORDS = {
    "новый", "новом", "создай", "разверни", "подними", "запусти", "установи",
    "для", "клиента", "сайт", "лендинг", "пожалуйста", "уже", "мой",
}


def _slug(text: str) -> str:
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    out = "".join(translit.get(c.lower(), c.lower()) for c in text)
    out = re.sub(r"[^a-z0-9]+", "-", out).strip("-")
    return out or "site"


def _find_domain(text: str) -> Optional[str]:
    m = _DOMAIN_RE.search(text)
    return m.group(1).lower() if m else None


def _find_client(text: str) -> Optional[str]:
    m = _CLIENT_RE.search(text)
    return m.group(1) if m else None


def _find_server_mention(text: str) -> Optional[str]:
    m = _SERVER_RE.search(text)
    if m and m.group(1).lower() not in _SERVER_STOPWORDS:
        return m.group(1)
    return None


def rules_plan(text: str, client: TimewebClient) -> dict:
    """Планировщик правил: понимает типовые запросы на русском без LLM."""
    low = text.lower()
    steps: list = []
    notes: list = []
    domain = _find_domain(text)
    client_name = _find_client(text)
    server_mention = _find_server_mention(text)
    slug = _slug(client_name or (domain.split(".")[0] if domain else "site"))

    wants = {
        "site": bool(re.search(r"сайт|лендинг|landing|страниц|веб-сайт", low)),
        "postgres": bool(re.search(r"postgres|pgsql|постгрес", low)),
        "mysql": bool(re.search(r"mariadb|mysql|майскл|мариадб", low)),
        "redis": bool(re.search(r"redis|редис", low)),
        "nginx": bool(re.search(r"nginx|нгинкс", low)),
        "https": bool(re.search(r"https|ssl|сертификат", low)),
        "managed_db": bool(re.search(r"управляем|dbaas|облачн\w+ базу|кластер баз", low)),
        "new_server": bool(_NEW_SERVER_RE.search(text)),
        "git": bool(re.search(r"из\s+(?:github|git|репозитори)", low)),
        "docker_app": bool(re.search(r"docker|докер|контейнер", low)),
        "diag": bool(re.search(r"диагностик|конфигураци\w+ сервера|nproc|fdisk", low)),
        "status": bool(re.search(r"покажи\s+сервер|что\s+на\s+аккаунте|список\s+сервер", low)),
    }
    wants["dns_record"] = bool(re.search(r"запис(?:ь|и)|dns", low)) and not wants["site"]

    # --- просто справка о состоянии ---
    if wants["status"]:
        return {
            "summary": "Показать состояние аккаунта и серверов",
            "steps": [{"action": "servers.list", "name": "Список серверов"}],
        }

    # --- диагностика конфигурации сервера ---
    if wants["diag"] and not any([wants["site"], wants["postgres"], wants["mysql"], wants["redis"], wants["git"]]):
        srv = server_mention or (api.list_servers(client) or [{}])[0].get("name")
        return {
            "summary": "Диагностика конфигурации сервера для поддержки",
            "steps": [
                {"action": "check", "name": "Ядра CPU (nproc)", "with": {"kind": "command", "server": srv, "command": "nproc"}},
                {"action": "check", "name": "Память (free -h)", "with": {"kind": "command", "server": srv, "command": "free -h"}},
                {"action": "check", "name": "Диск (df -h)", "with": {"kind": "command", "server": srv, "command": "df -h"}},
                {"action": "check", "name": "Разделы (fdisk -l)", "with": {"kind": "command", "server": srv, "command": "fdisk -l"}},
            ],
        }

    # --- только DNS-записи ---
    if wants["dns_record"] and domain and not wants["site"]:
        m_ip = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
        if m_ip:
            steps.append({
                "action": "dns.add", "name": f"A-запись {domain}",
                "with": {"fqdn": domain, "type": "A", "value": m_ip.group(1), "ttl": 3600},
            })
        return {"summary": f"Добавить DNS-запись для {domain}", "steps": steps}

    # --- контекст сервера ---
    servers = api.list_servers(client)
    server_name = server_mention or (servers[0].get("name") if servers else None)
    need_create = wants["new_server"] or (server_name is None and not config.SSH_HOST)
    if need_create:
        server_name = server_name or f"{slug}-server"
    elif server_name is None:
        server_name = config.SSH_HOST  # деплоим на хост из .env

    ssh_target = {"server": server_name} if server_name and not _is_ip(server_name) else (
        {"host": server_name} if _is_ip(server_name) else {}
    )

    def step(action, name, with_, save=None, verify=None):
        needs_ssh = action.startswith("deploy.") or action.startswith("ssh.") or action == "check"
        base = dict(ssh_target) if needs_ssh and ssh_target else {}
        s = {"action": action, "name": name, "with": {**base, **(with_ or {})}}
        if save:
            s["save"] = save
        if verify:
            s["verify"] = verify
        steps.append(s)

    # Сервер нужен только если задача про деплой/контейнеры/сайт;
    # чисто управляемую БД (DBaaS) сервер не трогаем.
    site_effective = wants["site"] and domain is not None
    needs_server = bool(
        site_effective or wants["git"] or wants["docker_app"] or wants["nginx"]
        or (
            (wants["postgres"] or wants["mysql"] or wants["redis"])
            and not wants["managed_db"]
        )
    )
    if needs_server:
        if need_create:
            step(
                "servers.create", f"Создать сервер {server_name}",
                {"name": server_name, "os": "auto", "preset": "auto", "ssh_key": "auto", "wait": True},
                save={"as": "server"},
            )
        elif ssh_target.get("server"):
            step(
                "servers.create", f"Использовать сервер {server_name}",
                {"name": server_name, "wait": False},
                save={"as": "server"},
            )

    domain_in_panel = domain and any(d.get("fqdn") == domain for d in api.list_domains(client))
    if domain and domain_in_panel:
        step(
            "dns.add", f"A-запись {domain} на IP сервера",
            {"fqdn": domain, "type": "A", "value": "{{ server.ip }}", "ttl": 3600},
            save={"as": "dns_rec"},
        )
        step(
            "dns.add", f"CNAME www.{domain}",
            {"fqdn": f"www.{domain}", "type": "CNAME", "value": domain, "ttl": 3600},
        )
    elif domain:
        notes.append(f"Домен {domain} не привязан к аккаунту Timeweb — DNS-записи не добавлены (привяжите его в панели).")

    if wants["site"] and domain:
        step(
            "deploy.provision", f"Подготовить сервер {server_name or ''}".strip(),
            {"docker": True},
        )
        site_with = {
            "domain": domain,
            "ssl": True,
            "title": f"Сайт {client_name}" if client_name else None,
        }
        site_with = {k: v for k, v in site_with.items() if v is not None}
        step(
            "deploy.website", f"Развернуть сайт {domain} (nginx + HTTPS)",
            site_with,
            save={"as": "site"},
            verify={"kind": "http", "params": {"url": f"https://{domain}", "expect": 200, "retries": 6}},
        )

    if wants["postgres"]:
        if wants["managed_db"]:
            step(
                "db.create", f"Создать кластер PostgreSQL {slug}",
                {"name": slug, "type": "postgresql", "admin_login": "admin", "wait": True},
                save={"as": "database"},
            )
        else:
            step(
                "deploy.postgres", f"Запустить PostgreSQL (база {slug})",
                {"name": slug, "user": slug},
                save={"as": "postgres"},
                verify={"kind": "postgres", "params": {
                    "container": "{{ postgres.container }}", "user": "{{ postgres.user }}",
                    "password": "{{ postgres.password }}", "database": "{{ postgres.database }}"}},
            )

    if wants["mysql"]:
        if wants["managed_db"]:
            step(
                "db.create", f"Создать кластер MySQL {slug}",
                {"name": slug, "type": "mysql", "admin_login": "admin", "wait": True},
                save={"as": "database"},
            )
        else:
            step(
                "deploy.mysql", f"Запустить MySQL (база {slug})",
                {"name": slug, "user": slug},
                save={"as": "mysql"},
                verify={"kind": "mysql", "params": {
                    "container": "{{ mysql.container }}", "user": "{{ mysql.user }}",
                    "password": "{{ mysql.password }}", "database": "{{ mysql.database }}"}},
            )

    if wants["redis"]:
        if wants["managed_db"]:
            step(
                "db.create", f"Создать кластер Redis {slug}",
                {"name": f"{slug}-redis", "type": "redis", "admin_login": "default", "wait": True},
                save={"as": "database"},
            )
        else:
            step(
                "deploy.redis", "Запустить Redis",
                {"name": slug},
                save={"as": "redis"},
                verify={"kind": "redis", "params": {
                    "container": "{{ redis.container }}", "password": "{{ redis.password }}"}},
            )

    if wants["nginx"] and not wants["site"]:
        step("deploy.provision", "Установить nginx", {"docker": False})

    if wants["git"]:
        m_repo = re.search(r"(https?://\S+?\.git|git@\S+?\.git)", text)
        if m_repo and domain:
            step(
                "deploy.provision", "Подготовить сервер", {"docker": True},
            )
            step(
                "deploy.git", f"Развернуть приложение из git на {domain}",
                {"repo": m_repo.group(1), "branch": "main", "domain": domain, "port": 8000, "ssl": True},
                save={"as": "app"},
                verify={"kind": "http", "params": {"url": f"https://{domain}", "expect": 200, "retries": 6}},
            )
        elif m_repo:
            step(
                "deploy.git", "Развернуть приложение из git",
                {"repo": m_repo.group(1), "branch": "main"},
            )

    if not steps:
        raise runbook.RunbookError(
            "Не понял запрос. Скажите, что сделать, например:\n"
            "«Создай на сервере сайт для клиента Maria, PostgreSQL, Redis, "
            "Nginx и HTTPS на домене maria.ru»"
        )

    summary_parts = []
    if need_create:
        summary_parts.append(f"создать сервер {server_name}")
    if wants["site"] and domain:
        summary_parts.append(f"развернуть сайт {domain} с HTTPS")
    if wants["postgres"]:
        summary_parts.append("PostgreSQL")
    if wants["mysql"]:
        summary_parts.append("MySQL")
    if wants["redis"]:
        summary_parts.append("Redis")
    if wants["nginx"]:
        summary_parts.append("Nginx")
    summary = ", ".join(summary_parts) + "."
    if notes:
        summary += " " + " ".join(notes)
    return {"summary": summary, "steps": steps, "notes": notes}


def _is_ip(value: str) -> bool:
    return bool(re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", value))


# ---------------------------------------------------------------------- #
#  Главный вход планирования
# ---------------------------------------------------------------------- #
def plan(text: str, client: TimewebClient, force_llm: Optional[str] = None) -> dict:
    """Превращает текст в план. Возвращает {"engine", "summary", "steps", "warning"?}."""
    llm = None
    llm_error = None
    try:
        if force_llm and force_llm.lower() not in {"none", "rules", "auto"}:
            llm = LLM(provider=force_llm)
        else:
            llm = get_llm()
    except LLMError as e:
        llm_error = e

    if llm is not None:
        try:
            p = llm_plan(llm, text, client)
            p["engine"] = "llm"
            p["llm_provider"] = llm.provider
            p["llm_model"] = llm.model
            return p
        except Exception as e:  # noqa: BLE001 — падаем на анализатор правил
            p = rules_plan(text, client)
            p["engine"] = "rules"
            p["warning"] = f"LLM недоступен ({e}), использован встроенный анализатор"
            return p
    p = rules_plan(text, client)
    p["engine"] = "rules"
    if llm_error is not None and force_llm and force_llm.lower() not in {"none", "rules", "auto"}:
        p["warning"] = f"LLM не настроен ({llm_error}) — использован встроенный анализатор"
    return p


# ---------------------------------------------------------------------- #
#  Выполнение с проверками
# ---------------------------------------------------------------------- #
def verify_step(step: dict, ctx: dict, client: TimewebClient) -> Optional[dict]:
    """Выполняет проверку, прикреплённую к шагу. Возвращает результат или None."""
    spec = step.get("verify")
    if not isinstance(spec, dict):
        return None
    kind = spec.get("kind")
    params = runbook.render(spec.get("params") or {}, ctx)
    ssh = None
    if kind not in {"http", "dns"}:
        # SSH-таргет: из параметров шага (уже отрендеренных) или из проверки
        target = {**runbook.render(step.get("with") or {}, ctx), **params}
        try:
            ssh = runbook.ssh_for(target, client)
        except SSHError as e:
            return {"ok": False, "detail": f"нет SSH: {e}"}
    return verify.run_check(kind, params, ssh=ssh)


def run_request(
    text: str,
    client: TimewebClient,
    *,
    confirm: bool = True,
    force_llm: Optional[str] = None,
    verbose: bool = False,
    preapproved_plan: Optional[dict] = None,
) -> dict:
    """Полный пайплайн: понять → план → (подтверждение) → выполнить →
    проверить → отчёт.

    preapproved_plan — уже подтверждённый план (например, из веб-панели);
    в этом случае этап подтверждения пропускается.
    """
    if preapproved_plan is not None:
        p = validate_plan(preapproved_plan)
        p.setdefault("engine", "web")
    else:
        p = plan(text, client, force_llm=force_llm)

    steps = p["steps"]

    if confirm:
        print(f"\nПлан ({p['engine']}): {p.get('summary', '')}")
        for i, s in enumerate(steps, 1):
            print(f"  {i}. {s.get('name') or s.get('action')}  [{s.get('action')}]")
        import sys
        if sys.stdin.isatty():
            answer = input("\nВыполнить? [y/N]: ").strip().lower()
            if answer not in {"y", "yes", "д", "да"}:
                raise runbook.RunbookError("Отменено пользователем")
        elif not (config.AUTO_YES or config.get_bool("TW_YES")):
            raise runbook.RunbookError("Требуется подтверждение: --yes или TW_YES=1")

    ctx: dict = {"vars": {}, "saved": {}}
    checks: list = []
    for i, step in enumerate(steps, 1):
        try:
            result = runbook.execute_step(client, ctx, step, verbose=verbose)
        except runbook.RunbookError as e:
            checks.append({"step": i, "name": step.get("name") or step.get("action"), "ok": False, "error": str(e), "kind": "execute"})
            return {
                "engine": p["engine"], "summary": p.get("summary"),
                "plan": steps, "checks": checks, "saved": ctx["saved"],
                "report": f"❌ План прерван на шаге {i}: {e}", "failed": True,
            }
        check = verify_step(step, ctx, client)
        if check is not None:
            label = check.get("detail", "")
            print(f"[verify] {step.get('name', '')}: {'✓' if check['ok'] else '✗'} {label[:150]}", flush=True)
            checks.append({
                "step": i, "name": step.get("name") or step.get("action"),
                "kind": step["verify"].get("kind"), "ok": check["ok"], "detail": label,
            })

    all_ok = all(c.get("ok", False) for c in checks) and not any(c.get("kind") == "execute" for c in checks)
    report = make_report(p, checks, ctx["saved"], llm=get_llm() if p["engine"] == "llm" else None)
    return {
        "engine": p["engine"], "summary": p.get("summary"),
        "warning": p.get("warning"), "plan": steps, "checks": checks,
        "saved": ctx["saved"], "report": report, "failed": not all_ok,
    }


# ---------------------------------------------------------------------- #
#  Отчёт
# ---------------------------------------------------------------------- #
def _structured_report(plan: dict, checks: list, saved: dict) -> str:
    lines = [f"Задача: {plan.get('summary', '')}", ""]
    for c in checks:
        mark = "✅" if c.get("ok") else "❌"
        lines.append(f"{mark} {c.get('name', '')} — {c.get('detail', c.get('error', ''))}")
    if not checks:
        lines.append("ℹ️ Автоматические проверки не применялись (ресурс создан, см. доступы ниже).")
    for key, value in saved.items():
        if not isinstance(value, dict):
            continue
        # сохранённый результат обычно обёрнут в ключ со своим именем
        inner = value.get(key)
        info = inner if isinstance(inner, dict) else value
        creds = []
        for field in ("password", "user", "login", "host", "port", "database", "container", "ip", "type", "status"):
            if info.get(field):
                creds.append(f"{field}={info[field]}")
        if creds:
            lines.append(f"ℹ️ {key}: " + ", ".join(str(c) for c in creds))
    lines.append("")
    lines.append("Готово. Подробности — в логе выше.")
    return "\n".join(lines)


def make_report(plan: dict, checks: list, saved: dict, llm: Optional[LLM] = None) -> str:
    if llm is not None:
        try:
            summary = llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Ты — агент управления серверами. Напиши краткий отчёт по-русски (3-7 предложений): "
                            "что было сделано, что проверено и с каким результатом, и как пользоваться результатом "
                            "(адреса, доступы). Не выдумывай деталей, которых нет в данных."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"план": plan.get("summary"), "проверки": checks, "результаты": saved},
                            ensure_ascii=False, default=str,
                        ),
                    },
                ],
                temperature=0.4,
                json_mode=False,
            )
            return summary.strip()
        except Exception:  # noqa: BLE001
            pass
    return _structured_report(plan, checks, saved)
