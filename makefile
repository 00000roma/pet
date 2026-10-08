.PHONY: help build up down restart logs shell menu cli ps health clean

help:
	@echo "make build / up / down / restart / logs / shell / menu / ps / health / clean"

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