.PHONY: help build up down restart logs shell menu cli ps health clean install

help:
	@echo "make build / up / down / restart / logs / shell / menu / ps / health / clean / install"

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

shell:
	docker compose exec xray-manager bash

menu:
	docker compose exec -it xray-manager python main.py

cli:
	docker compose exec xray-manager python main.py $(CMD)

ps:
	docker compose ps

health:
	@curl -s http://localhost:8080/health && echo ""

clean:
	docker compose down -v
	-docker rmi xray-manager:latest

install:
	sudo install -m 0755 script/xray-manager /usr/local/bin/xray-manager
	sudo ln -sf /usr/local/bin/xray-manager /usr/local/bin/xrm
	@echo "OK: команда xray-manager установлена (alias xrm)."