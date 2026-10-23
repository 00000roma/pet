# Xray Manager — управление Xray (VLESS + Reality + XHTTP) и подписками

**Xray Manager** — консольная утилита + HTTP-сервис для управления Xray-серверами и раздачи персональных подписок пользователям через клиент **Happ**.

Проект создан для администраторов, которые хотят:
- быстро развернуть Xray на новых серверах,
- импортировать существующие без изменения конфигов,
- управлять пользователями из одной консоли,
- раздавать **одну короткую ссылку**, которая настраивает клиент автоматически.

---

## ⚡ Установка, запуск и обновление (кратко)

### Установка одной командой (Linux-сервер с Docker)

```bash
curl -fsSL https://raw.githubusercontent.com/00000roma/pet/refs/heads/main/script/install.sh | sudo bash
```

Скрипт сам:
1. Установит Docker (если его нет) и скачает образ `ghcr.io/00000roma/xray-manager:latest`.
2. Создаст `/opt/xray-manager`, файл `.env` и `data/routing_custom.json`.
3. Запустит контейнер и поставит команду `xray-manager` (alias `xrm`).

### Запуск меню

```bash
xray-manager
```

Без обёртки — то же самое напрямую:

```bash
cd /opt/xray-manager && sudo docker compose exec -it xray-manager python main.py
```

### Обновление

```bash
cd /opt/xray-manager
sudo docker compose pull
sudo docker compose up -d
```

> Если собираешь образ из исходников (разработка) — вместо `pull`:
> `git pull && sudo docker compose up -d --build`

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
git clone https://github.com/<your-username>/xray-manager.git
cd xray-manager
```

### 2. Настройка `.env`

Скопируй `.env.example` → `.env`:

```bash
cp .env.example .env
```

**Заполни**:

```env
PUBLIC_URL=https://sub.example.com
HTTP_PORT=8080
SSH_DIR=/root/.ssh
DEFAULT_SSH_USER=root
DEFAULT_SSH_PORT=22
DEFAULT_SSH_KEY=/root/.ssh/id_ed25519
LOG_LEVEL=INFO
```

- **`PUBLIC_URL`** — публичный домен, на котором работает сервис подписок (HTTPS).
- **`SSH_DIR`** — путь к папке с SSH-ключами **на хосте** (внутри Docker-контейнера это всегда `/root/.ssh`).

### 3. Подготовка SSH-ключа

**Сгенерируй** **SSH-ключ** **на** **машине** **админа** (**если** **ещё** **нет**):

```bash
ssh-keygen -t ed25519 -C "xray-manager" -f ~/.ssh/id_ed25519 -N ""
```

**Публичную** **часть** **отдай** **админу** **серверов** — **он** **добавит** **её** **в** `~/.ssh/authorized_keys` **на** **root**.

**Проверь** **доступ**:

```bash
ssh -i ~/.ssh/id_ed25519 root@<SERVER_IP> "echo OK"
```

### 4. Развёртывание Xray на сервере

**Установи** **Docker** **на** **сервере** (**Ubuntu**):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

**Скопируй** **SSH-ключ** **на** **сервер**:

```bash
scp ~/.ssh/id_ed25519 root@<SERVER_IP>:/root/.ssh/id_ed25519
ssh root@<SERVER_IP> "chmod 700 /root/.ssh && chmod 600 /root/.ssh/id_ed25519"
```

**Склонируй** **проект**:

```bash
git clone https://github.com/<your-username>/xray-manager.git
cd xray-manager
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

### Короткая команда `xray-manager`

После установки доступна короткая команда `xray-manager` — её можно запускать из **любой** папки. Это обёртка над `docker compose exec`, поэтому вместо длинной строки

```bash
cd /opt/xray-manager && sudo docker compose exec -it xray-manager python main.py <КОМАНДА>
```

достаточно писать коротко:

```bash
xray-manager <КОМАНДА>
```

**Алиасы:**

| Команда | Что делает |
|---|---|
| `xray-manager` | Открыть интерактивное меню |
| `xray-manager <КОМАНДА>` | Выполнить команду CLI (например `server list`) |
| `xray-manager run <КОМАНДА>` | То же самое — `run` необязательный синоним |
| `xrm` | Сокращение для `xray-manager` (создаётся при установке) |

> Хочешь ещё короче — добавь в `~/.bashrc` (или `~/.zshrc`) строку `alias xr='xray-manager'` и выполни `source ~/.bashrc`.

Полная справка по всем командам:

```bash
xray-manager --help
```

### CLI-команды

**Серверы** (`server`):

| Команда | Описание |
|---|---|
| `xray-manager server list` | Список серверов из БД |
| `xray-manager server add --host <IP> --key <KEY> [--name <N>] [--dest <D>]` | Развернуть Xray с нуля на чистом сервере |
| `xray-manager server import --host <IP> --key <KEY> [--name <N>]` | Импортировать существующий сервер (read-only) |
| `xray-manager server status --id <ID>` | Статус сервера (порт, ping, конфиг) |
| `xray-manager server edit --id <ID> [--port] [--dest] [--sni] [--network xhttp/grpc] [--fingerprint] [--xhttp-path] [--xhttp-mode] [--xhttp-host]` | Изменить параметры сервера |

**Пользователи** (`user`):

| Команда | Описание |
|---|---|
| `xray-manager user add --email <EMAIL> --servers all` | Добавить пользователя на все серверы |
| `xray-manager user add --email <EMAIL> --servers 1,2,3` | Добавить на конкретные серверы |
| `xray-manager user add-bulk --file data/users.txt --servers all` | Пакетное создание (один email на строку) |
| `xray-manager user list [--with-links]` | Список пользователей |
| `xray-manager user show --email <EMAIL>` | Детали пользователя (UUID, токен, серверы) |
| `xray-manager user remove --email <EMAIL> [--yes]` | Удалить пользователя |
| `xray-manager user export-links [--output data/all_users.links.txt]` | Выгрузить `email<TAB>ссылка` в файл |

**Подписки** (`sub`):

| Команда | Описание |
|---|---|
| `xray-manager sub url --email <EMAIL>` | **Короткая ссылка** `https://.../go/{token}` |
| `xray-manager sub url --all` | Все короткие ссылки (таблица) |
| `xray-manager sub show --email <EMAIL>` | `vless://` ссылки пользователя |
| `xray-manager sub show --email <EMAIL> --base64` | Подписка в Base64 |
| `xray-manager sub happ --email <EMAIL>` | Happ routing deep-link |

**Сервис** (`serve`):

| Команда | Описание |
|---|---|
| `xray-manager serve run` | Запустить HTTP-сервер подписок вручную (обычно уже запущен контейнером) |

> Без обёртки те же команды запускаются напрямую:
> `sudo docker compose exec -it xray-manager python main.py ...`

### Интерактивное меню

```bash
xray-manager
```

Откроется **меню** с разделами: **Серверы**, **Пользователи**, **HTTP-сервер**.

> Меню требует настоящий TTY. При запуске из скрипта/CI (без TTY) используй команды напрямую, например `xray-manager server list`.

При запуске меню выводятся пути к ключевым файлам (БД, правила routing, `.env`, файл для `add-bulk`). Пункт **«Показать ссылки пользователя»** выводит одну короткую ссылку с токеном вида `https://.../go/{token}` — удобно копировать и отдавать пользователю.

### Настройка Reality fingerprint и XHTTP (на сервер)

У каждого сервера могут быть **свои** TLS-отпечаток (`fingerprint`) и **свои** XHTTP-параметры (`path`, `mode`, `host`). Значения хранятся в БД и подставляются в vless-ссылки и клиентский JSON-конфиг.

| Параметр | Значения | По умолчанию |
|---|---|---|
| `--fingerprint` | `chrome`, `safari`, `firefox`, `edge`, `ios`, `android`, `random` | `chrome` |
| `--xhttp-path` | путь (например `/xhttp`) | `/xhttp` |
| `--xhttp-mode` | `auto`, `packet-up`, `stream-one`, `stream-up` | `auto` |
| `--xhttp-host` | HTTP Host-заголовок (пустая строка — не указывать) | пусто |

**Примеры:**

```bash
# fingerprint + mode
xray-manager server edit --id <ID> --fingerprint safari --xhttp-mode stream-one

# path + host
xray-manager server edit --id <ID> --xhttp-path /cdn --xhttp-host cdn.example.com

# убрать Host
xray-manager server edit --id <ID> --xhttp-host ""
```

То же самое можно сделать через меню: `xray-manager` → «Серверы» → «Редактировать сервер» (пункты `fingerprint`, `XHTTP path`, `XHTTP mode`, `XHTTP host`).

После изменения Xray на сервере перезапускается автоматически; подписки обновятся при следующем обновлении у клиента.

> ⚠️ Если `config.json` правился на сервере **вручную** (не через `server edit`), выполни `server edit` ещё раз с нужными значениями — ссылки читают данные из БД, а не напрямую из `config.json`.

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

**Пример** **использования**:

```
https://sub.example.com/go/<USER_TOKEN>
```

Пользователь **тапает** → **Happ** → **подписка добавлена** → **routing применён автоматически**.

---

## 🗺 Правила маршрутизации

**Правила** **хранятся** **в** `data/routing_custom.json` **на** **сервере** (**не** **в** **git**).

### Структура

```json
{
    "replace_defaults": false,
    "direct_domains": ["domain:example.com", "domain:internal.example.com"],
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
- **`replace_defaults`** — **`true`** **отключает** **встроенные** **правила** (**полный** **контроль** **через** **этот** **файл**).

**Порядок** **применения** — `proxy → direct → block`:
1. `proxy_*` — **высший** **приоритет** (**принудительно** **через VPN**).
2. `direct_*` — **напрямую** (**если** **домен** **есть** **и** **в** **direct**, **и** **в** **block** — **пойдёт** **напрямую**).
3. `block_*` — **блокировка** (**самый** **низкий** **приоритет**).

### Полное управление списками (`replace_defaults`)

По умолчанию к твоим спискам из `routing_custom.json` **добавляются** встроенные
правила: в Happ — `geosite:private`, `geosite:category-gov-ru`, `geosite:category-ru`,
`geosite:cn`, `geoip:ru`, `geoip:cn`, `geosite:category-ads-all`; в JSON-конфиге Xray —
аналогичные стандартные direct/block-правила. Поэтому удаление записи из
`routing_custom.json` не убирает встроенное правило — оно «воскресает» из пресета.

Чтобы `routing_custom.json` стал **единственным источником** правил, добавь:

```json
{
    "replace_defaults": true,
    "direct_domains": [...],
    "direct_ips": [...],
    "block_domains": [...],
    "block_ips": [...],
    "proxy_domains": [...],
    "proxy_ips": [...]
}
```

При `"replace_defaults": true` встроенные списки игнорируются — остаются только твои.
⚠️ Не забудь оставить `geoip:private` / `geosite:private`, иначе локальная сеть
пойдёт через VPN.

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

## 🗂 Где что лежит

| Путь в контейнере | Путь на хосте | Что это |
|---|---|---|
| `data/xray_manager.db` | `/opt/xray-manager/data/xray_manager.db` | База данных (пользователи, серверы, токены) |
| `data/routing_custom.json` | `/opt/xray-manager/data/routing_custom.json` | Правила маршрутизации (direct / proxy / block) |
| `.env` | `/opt/xray-manager/.env` | Настройки (`PUBLIC_URL`, SSH и т.д.) |
| `data/users.txt` | `/opt/xray-manager/data/users.txt` | Файл для `user add-bulk` (один email на строку) |

Эти же пути показываются при запуске меню `xray-manager`.

---

## 🔧 Обслуживание

### Просмотр логов

```bash
docker compose logs -f xray-manager
```

### Обновление

**Установка через `install.sh` (образ из GHCR):**

```bash
cd /opt/xray-manager
sudo docker compose pull
sudo docker compose up -d
```

> Если обновлялась обёртка `xray-manager` (или alias `xrm`), обнови её вручную:
>
> ```bash
> sudo curl -fsSL https://raw.githubusercontent.com/00000roma/pet/refs/heads/main/script/xray-manager -o /usr/local/bin/xray-manager
> sudo chmod +x /usr/local/bin/xray-manager
> sudo ln -sf /usr/local/bin/xray-manager /usr/local/bin/xrm
> ```

**Разработка (сборка из исходников):**

```bash
git pull
sudo docker compose up -d --build
```

### Бэкап

**Что бэкапить** (всё в `/opt/xray-manager`):

| Файл | Что это |
|---|---|
| `data/xray_manager.db` | БД с пользователями и серверами |
| `data/routing_custom.json` | Правила маршрутизации |
| `.env` | Конфигурация |
| `/root/.ssh/id_ed25519` | SSH-ключ доступа к Xray-серверам |

```bash
cd /opt/xray-manager
tar czf xray-manager-backup-$(date +%F).tar.gz .env data/xray_manager.db data/routing_custom.json
```

---

## 🩺 Troubleshooting

### Подписка не открывается

1. **Проверь** `curl http://localhost:8080/health` **на** **сервере**.
2. **Проверь**, **что** **домен** (**PUBLIC_URL**) **резолвится** **в** **публичный** **IP**.
3. **Проверь** **HTTPS-сертификат** (**NPM**, **Caddy**).

### Happ не применяет routing

1. **Проверь**, **что** **в** `/sub/{token}/xray.json` **есть** **заголовок** `routing:`.
2. **Проверь**, **что** **профиль** **появился** **в** **Happ** → **Routing**.
3. **Если** **не** **появился** — **примени** **вручную**:
   ```
   https://sub.example.com/sub/{token}/happ-routing
   ```

### Флаги стран не отображаются

- **Happ** **читает** **имя** **из** `#label` **в** **Base64-подписке**.
- **Убедись**, **что** **пользователь** **использует** `/sub/{token}`, **а** **не** `/sub/{token}/xray.json`.

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
- **Проверь**, **что** `routing_custom.json` — **валидный** **JSON**:
  ```bash
  python3 -m json.tool data/routing_custom.json
  ```

---

## 📁 Структура проекта

```
xray-manager/
├── main.py                     # Точка входа CLI
├── requirements.txt
├── dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
│
├── script/
│   ├── install.sh              # Установка одной командой
│   └── xray-manager            # Обёртка для запуска из любой папки
│
├── core/                       # Бизнес-логика
│   ├── ssh_client.py
│   ├── config_parser.py
│   ├── xray_config_builder.py
│   ├── happ_routing.py
│   ├── subscription.py
│   ├── links.py
│   ├── user_manager.py
│   ├── server_manager.py
│   ├── installer.py
│   ├── reality.py
│   └── flags.py
│
├── cli/
│   ├── menu.py
│   ├── server_commands.py
│   ├── user_commands.py
│   ├── sub_commands.py
│   └── serve_commands.py
│
├── services/
│   ├── server_runner.py
│   ├── subscription_updater.py
│   └── api/
│       ├── app.py
│       └── routes.py
│
├── db/
│   ├── models.py
│   └── database.py
│
├── templates/
│   ├── install_xray.sh
│   └── xray_config_base.json
│
└── data/
    ├── xray_manager.db          # БД (создаётся при первом запуске)
    ├── routing_custom.json      # Правила маршрутизации
    └── users.txt                # Файл для add-bulk (один email на строку)
```

---

## 📜 Лицензия

MIT License — используй, модифицируй, распространяй свободно.
