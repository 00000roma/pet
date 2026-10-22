#!/usr/bin/env bash
#
# Xray Manager — установка одной командой из GHCR
#
# Использование:
#   curl -fsSL https://raw.githubusercontent.com/00000roma/xray-manager/main/scripts/install.sh | sudo bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------- Настройки ----------
GITHUB_USER="${GITHUB_USER:-00000roma}"
REPO_NAME="${REPO_NAME:-pet}"
IMAGE="ghcr.io/${GITHUB_USER}/xray-manager:latest"
INSTALL_DIR="${INSTALL_DIR:-/opt/xray-manager}"
COMPOSE_URL="https://raw.githubusercontent.com/${GITHUB_USER}/${REPO_NAME}/refs/heads/main/docker-compose.yml"
ENV_EXAMPLE_URL="https://raw.githubusercontent.com/${GITHUB_USER}/${REPO_NAME}/refs/heads/main/.env.example"
ROUTING_EXAMPLE_URL="https://raw.githubusercontent.com/${GITHUB_USER}/${REPO_NAME}/refs/heads/main/routing_custom.example.json"

# ---------- Проверки ----------
if [ "$EUID" -ne 0 ]; then
    error "Запусти через sudo."
    exit 1
fi

if [ -f /etc/os-release ]; then
    . /etc/os-release
    info "ОС: $ID $VERSION_ID"
else
    error "Не удалось определить ОС."
    exit 1
fi

# ---------- Docker ----------
if ! command -v docker >/dev/null 2>&1; then
    info "Устанавливаю Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi
ok "Docker: $(docker --version)"

if ! docker compose version >/dev/null 2>&1; then
    error "docker compose не найден."
    exit 1
fi

# ---------- Папка установки ----------
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Создаём data/ и копируем шаблон routing_custom, если его нет
mkdir -p data
if [ ! -f data/routing_custom.json ]; then
    if curl -fsSL "$ROUTING_EXAMPLE_URL" -o data/routing_custom.json; then
        ok "Создан data/routing_custom.json из шаблона."
    else
        warn "Не удалось скачать routing_custom.example.json. Создай data/routing_custom.json вручную."
    fi
fi

# ---------- docker-compose.yml ----------
if [ ! -f docker-compose.yml ]; then
    info "Скачиваю docker-compose.yml..."
    curl -fsSL "$COMPOSE_URL" -o docker-compose.yml
fi
ok "docker-compose.yml на месте."

# ---------- .env ----------
if [ ! -f .env ]; then
    info "Создаю .env..."
    curl -fsSL "$ENV_EXAMPLE_URL" -o .env.example 2>/dev/null || true

    read -rp "Путь к SSH-ключам на этом сервере [/root/.ssh]: " ssh_dir
    ssh_dir="${ssh_dir:-/root/.ssh}"

    read -rp "Публичный URL сервиса (например https://update.rktv.ru) []: " public_url
    public_url="${public_url:-}"

    cat > .env <<EOF
PUBLIC_URL=${public_url}
HTTP_PORT=8080
SSH_DIR=${ssh_dir}
DEFAULT_SSH_USER=root
DEFAULT_SSH_PORT=22
DEFAULT_SSH_KEY=/root/.ssh/id_ed25519
LOG_LEVEL=INFO
EOF
    ok ".env создан."
fi

# ---------- SSH-ключи ----------
ssh_dir=$(grep '^SSH_DIR=' .env | cut -d'=' -f2)
ssh_dir="${ssh_dir:-/root/.ssh}"

if [ ! -d "$ssh_dir" ] || [ -z "$(ls -A "$ssh_dir" 2>/dev/null)" ]; then
    warn "Папка $ssh_dir пуста."
    read -rp "Сгенерировать новый SSH-ключ? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        mkdir -p "$ssh_dir"
        chmod 700 "$ssh_dir"
        ssh-keygen -t ed25519 -f "$ssh_dir/id_ed25519" -N '' -C "xray-manager"
        chmod 600 "$ssh_dir/id_ed25519"
        ok "Ключ: $ssh_dir/id_ed25519"
        echo "  Публичный ключ (добавь его на управляемые серверы):"
        cat "$ssh_dir/id_ed25519.pub"
    fi
fi

# ---------- Pull образа ----------
info "Скачиваю образ $IMAGE ..."
docker pull "$IMAGE"
ok "Образ загружен."

# ---------- Запуск ----------
info "Запускаю контейнер..."
docker compose up -d

# ---------- Ожидание ----------
info "Жду готовности..."
for i in {1..30}; do
    if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
    ok "Приложение работает."
else
    warn "Проверь логи: cd $INSTALL_DIR && docker compose logs -f"
fi

# ---------- Обёртка xray-manager ----------
info "Устанавливаю команду xray-manager..."
WRAPPER_URL="https://raw.githubusercontent.com/${GITHUB_USER}/${REPO_NAME}/refs/heads/main/script/xray-manager"
if curl -fsSL "$WRAPPER_URL" -o /usr/local/bin/xray-manager; then
    chmod +x /usr/local/bin/xray-manager
    ln -sf /usr/local/bin/xray-manager /usr/local/bin/xrm
    ok "Готова команда: xray-manager (alias xrm)."
else
    warn "Не удалось скачать обёртку xray-manager (пропускаю)."
fi

# ---------- Финальное сообщение ----------
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}========================================"
echo -e "  Xray Manager установлен!"
echo -e "========================================${NC}"
echo ""
echo "Установлен в: $INSTALL_DIR"
echo ""
echo "Меню (из любой папки):"
echo -e "  ${BLUE}xray-manager${NC}"
echo ""
echo "HTTP:"
echo -e "  ${BLUE}http://$LOCAL_IP:8080/docs${NC}"
echo ""
echo "Логи:"
echo -e "  ${BLUE}cd $INSTALL_DIR && docker compose logs -f${NC}"
echo ""
