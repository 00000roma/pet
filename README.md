Сначала создаем ключи для ssh

curl -fsSL https://raw.githubusercontent.com/00000roma/pet/refs/heads/main/script/install.sh | sudo bash

sudo docker compose exec -it xray-manager python main.py

Редактирование правил routing
sudo nano /opt/xray-manager/data/routing_custom.json


# Reactive — управление Xray (VLESS + Reality + XHTTP) и подписками

**Reactive** — это консольная утилита + HTTP-сервис для управления Xray-серверами и раздачи персональных подписок пользователям через клиенты **Happ**, **Nekoray**, **v2rayNG**.

Проект создан для внутреннего использования: позволяет быстро развернуть Xray на новом сервере, импортировать существующие серверы, управлять пользователями и раздавать им **одну короткую ссылку**, которая автоматически настраивает подключение и правила маршрутизации.

---

## 🚀 Возможности

- **Развёртывание Xray одной командой** на чистом сервере (Ubuntu).
- **Импорт существующих Xray-серверов** без изменения их конфигов (read-only).
- **Управление пользователями** (создание, удаление, пакетное создание из файла).
- **Персональные токены** в URL подписок — email пользователя не светится.
- **Генерация Base64 и JSON подписок** для разных клиентов.
- **Флаги стран** в именах серверов (Happ отображает их как иконки).
- **Правила маршрутизации** (direct / proxy / block) — как глобально, так и для конкретных серверов.
- **Автоматическое применение правил** в Happ через HTTP-заголовок `routing`.
- **Установка в Docker** — изолировано, переносимо, обновление одной командой.

---

## ⚙️ Требования

**На машине администратора:**
- **Windows / macOS / Linux**
- **Docker Desktop** (для сборки образа) или **Linux + Docker Engine**
- **SSH-ключ** для доступа к управляемым серверам
- **Git**

**На управляемых серверах:**
- **Ubuntu 22.04+** (или Debian 12+)
- **Root-доступ** по SSH-ключу
- **Открытый порт Xray** (обычно 443)

---

## 📦 Быстрый старт

### 1. Клонирование проекта

```bash
git clone https://github.com/00000roma/pet.git
cd pet
```

### 2. Настройка `.env`

Скопируй `.env.example` → `.env`:

```bash
cp .env.example .env
```

**Заполни**:

```env
PUBLIC_URL=https://update.rktv.ru
HTTP_PORT=8080
SSH_DIR=/root/.ssh
DEFAULT_SSH_USER=root
DEFAULT_SSH_PORT=22
DEFAULT_SSH_KEY=/root/.ssh/id_ed25519
LOG_LEVEL=INFO
```

- **`PUBLIC_URL`** — публичный домен, на котором работает сервис подписок (HTTPS).
- **`SSH_DIR`** — путь к папке с SSH-ключами **на хосте** (внутри Docker-контейнера это всегда `/root/.ssh`).

### 3. Установка на управляемый сервер (VPS)

Установи **Docker** на VPS (**Ubuntu**):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

**Скопируй SSH-ключ** на VPS (**с машины админа**):

```bash
scp ~/.ssh/id_ed25519 root@<VPS_IP>:/root/.ssh/id_ed25519
ssh root@<VPS_IP> "chmod 700 /root/.ssh && chmod 600 /root/.ssh/id_ed25519"
```

### 4. Установка Reactive на VPS

**Склонируй** проект **на** VPS:

```bash
git clone https://github.com/00000roma/pet.git
cd pet
cp .env.example .env
nano .env   # укажи PUBLIC_URL
```

**Запусти**:

```bash
docker compose up -d --build
```

**Проверь**:

```bash
docker compose ps
curl http://localhost:8080/health
# → {"status":"ok"}
```

---

## 🖥 Использование

### CLI-команды

**Показать список команд**:

```bash
docker compose exec xray-manager python main.py --help
```

**Основные**:

| Команда | Описание |
|---|---|
| `python main.py` | Открыть интерактивное меню |
| `python main.py server list` | Список серверов |
| `python main.py server add --host <IP> --key <KEY> --name <NAME>` | Развернуть новый Xray |
| `python main.py server import --host <IP> --key <KEY> --name <NAME>` | Импортировать существующий |
| `python main.py user add --email <EMAIL> --servers all` | Добавить пользователя |
| `python main.py user add-bulk --file users.txt --servers all` | Пакетное создание |
| `python main.py user list` | Список пользователей |
| `python main.py user list --with-links` | Список с ссылками на подписки |
| `python main.py user show --email <EMAIL>` | Детали пользователя |
| `python main.py user export-links` | Выгрузить все ссылки в файл |
| `python main.py user remove --email <EMAIL>` | Удалить пользователя |

### Интерактивное меню

```bash
docker compose exec -it xray-manager python main.py
```

Откроется **меню** с разделами: **Серверы**, **Пользователи**, **Подписки**, **HTTP-сервер**.

---

## 🌐 Эндпоинты HTTP-сервиса

| Эндпоинт | Что возвращает |
|---|---|
| `GET /health` | `{"status": "ok"}` |
| `GET /go/{token}` | HTML-страница с кнопками добавления подписки в Happ |
| `GET /sub/{token}` | Base64-подписка (vless-ссылки с флагами) |
| `GET /sub/{token}/xray.json` | JSON-конфиг Xray (с правилами routing) |
| `GET /sub/{token}/happ-routing` | HTML-страница с кнопкой «Открыть в Happ» для routing |
| `GET /sub/{token}/happ-routing/raw` | Сырой deep link `happ://routing/onadd/...` |

**Пример использования**:

```
https://update.rktv.ru/go/q374rZmnb70nreOnmMrWqQ39Q4ovMQRZ
```

Пользователь **тапает** → **Happ** → **подписка добавлена** → **routing применён автоматически**.

---

## 🗺 Правила маршрутизации

**Правила** хранятся в `data/routing_custom.json` **на** VPS (**не** **в** **git**).

### Структура

```json
{
    "direct_domains": ["domain:rktv.ru", "domain:jira.rktv.ru"],
    "direct_ips": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
    "block_domains": [],
    "block_ips": [],
    "proxy_domains": [
        "domain:telegram.org",
        "domain:chatgpt.com",
        "domain:youtube.com",
        "domain:instagram.com"
    ],
    "proxy_ips": [
        "geoip:telegram",
        "91.108.4.0/22",
        "149.154.160.0/20"
    ]
}
```

**Что** **куда**:
- **`direct_domains`** — **эти** **домены** **идут** **напрямую** (**мимо VPN**).
- **`direct_ips`** — **IP-диапазоны** **напрямую**.
- **`block_domains`** — **блокируются** (**реклама**, **трекеры**).
- **`proxy_domains`** — **принудительно** **через VPN**.
- **`proxy_ips`** — **IP** **через VPN** (**для** **сервисов** **вроде** **Telegram**).

### Формат доменов

| Формат | Что значит |
|---|---|
| `domain:example.com` | `example.com` + **все** **поддомены** |
| `full:example.com` | **Только** `example.com` |
| `regexp:^ads\.` | **Регулярное** **выражение** |
| `geoip:ru` | **Все** **российские** **IP** |
| `geosite:category-ads-all` | **Встроенный** **список** **рекламы** |

### Применение изменений

**После** **правки** `routing_custom.json`:
1. **Не** **надо** **перезапускать** **контейнер**.
2. **Пользователи** **обновляют** **подписку** **в** **Happ** → **получают** **новые** **правила**.

---

## 🔧 Обслуживание

### Просмотр логов

```bash
docker compose logs -f xray-manager
```

### Обновление образа

```bash
git pull
docker compose up -d --build
```

### Бэкап

**Бэкапить** **надо**:
- `data/xray_manager.db` — **БД** **с** **пользователями** **и** **серверами**.
- `data/routing_custom.json` — **правила** **routing**.
- `.env` — **конфиг**.
- `/root/.ssh/id_ed25519` — **SSH-ключ** (**доступ** **к** **Xray-серверам**).

**Скрипт** **бэкапа** — `scripts/backup.sh`.

---

## 🩺 Troubleshooting

### Подписка не открывается

1. **Проверь** `curl http://localhost:8080/health` **на** VPS.
2. **Проверь**, что домен (**PUBLIC_URL**) **резолвится** **в** **публичный** **IP**.
3. **Проверь** HTTPS-**сертификат** (**NPM**, **Caddy**).

### Happ не применяет routing

1. **Проверь**, что в `/sub/{token}/xray.json` **есть** **заголовок** `routing:`.
2. **Проверь**, что профиль `Reactive` **появился** **в** **Happ** → **Routing**.
3. **Если** **не** **появился** — **примени** **вручную**:
   ```
   https://update.rktv.ru/sub/{token}/happ-routing
   ```

### Флаги стран не отображаются

- **Happ** **читает** **имя** **из** `#label` **в** **Base64**-подписке.
- **Убедись**, что **пользователь** **использует** `/sub/{token}`, **а** **не** `/sub/{token}/xray.json`.

### Telegram Desktop не работает

- **Добавь** **IP-диапазоны** **Telegram** **в** `proxy_ips`:
  ```json
  "91.108.4.0/22",
  "149.154.160.0/20",
  "geoip:telegram"
  ```
- **Или** **в** **Telegram** **Desktop** **→** **Настройки** **→** **Продвинутые** **→** **Тип** **подключения** → **SOCKS5** → `127.0.0.1:10808`.

### ChatGPT/YouTube не работают

- **Добавь** **домены** **в** `proxy_domains`:
  ```json
  "domain:chatgpt.com",
  "domain:openai.com",
  "domain:youtube.com"
  ```
- **Проверь**, **что** `routing_custom.json` — **валидный** JSON:
  ```bash
  python3 -m json.tool data/routing_custom.json
  ```

---

## 📁 Структура проекта

```
xray-manager/
├── main.py                     # Точка входа CLI
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
│
├── core/                       # Бизнес-логика
│   ├── ssh_client.py           # Обёртка над Fabric
│   ├── config_parser.py        # Парсинг config.json
│   ├── xray_config_builder.py  # Генерация JSON-подписки
│   ├── happ_routing.py         # Генерация deep link для Happ
│   ├── subscription.py         # Генерация vless:// ссылок
│   ├── user_manager.py         # CRUD пользователей
│   ├── server_manager.py       # Импорт/деплой серверов
│   ├── installer.py            # Установка Xray (wget)
│   ├── reality.py              # Генерация ключей Reality
│   └── flags.py                # Флаги стран
│
├── cli/                        # CLI-команды
│   ├── menu.py                 # Интерактивное меню
│   ├── server_commands.py
│   ├── user_commands.py
│   ├── sub_commands.py
│   └── serve_commands.py
│
├── services/                   # HTTP-сервис
│   └── api/
│       ├── app.py              # FastAPI-приложение
│       └── routes.py           # Эндпоинты
│
├── db/                         # База данных
│   ├── models.py
│   └── database.py
│
├── templates/
│   └── xray_config_base.json   # Шаблон конфига Xray
│
└── data/                       # Данные (не в git)
    ├── xray_manager.db
    ├── routing_custom.json
    ├── users.txt
    ├── users.links.txt
    └── logs/
```

---

## 📜 Лицензия

MIT License — используй, модифицируй, распространяй свободно.