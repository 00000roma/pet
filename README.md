Сначала создаем ключи для ssh

curl -fsSL https://raw.githubusercontent.com/00000roma/pet/refs/heads/main/script/install.sh | sudo bash

sudo docker compose exec -it xray-manager python main.py

Редактирование правил routing
sudo nano /opt/xray-manager/data/routing_custom.json
