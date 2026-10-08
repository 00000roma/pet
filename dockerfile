# Dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Системные пакеты: ssh-клиент, curl, gcc для cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-client \
        curl \
        gcc \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Python-зависимости отдельным слоем (кэшируется при пересборке)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код
COPY . .

# Структура данных
RUN mkdir -p /app/data/logs /app/data/backups

EXPOSE 8080

# По умолчанию — HTTP-сервер подписок
CMD ["uvicorn", "services.api.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info"]