#!/bin/bash
# fix_arp.sh — обход особенности VPS: контейнеры не отвечают на ARP-запросы
# хоста (host -> container «виснет»), поэтому прописываем статические
# neigh-записи для контейнеров стека. Запускать после docker compose up -d.
set -u
for c in heatnet-db heatnet-geo-engine heatnet-app; do
  IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$c" 2>/dev/null)
  MAC=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}' "$c" 2>/dev/null)
  [ -z "$IP" ] && continue
  BR=$(ip route get "$IP" | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)
  [ -z "$BR" ] && { echo "arp: $c — не найден интерфейс для $IP"; continue; }
  ip neigh replace "$IP" lladdr "$MAC" dev "$BR" \
    && echo "arp: $c $IP $MAC dev $BR"
done
