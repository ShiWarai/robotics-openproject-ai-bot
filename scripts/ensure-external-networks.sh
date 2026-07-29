#!/usr/bin/env sh
# Создаёт внешние сети, если их ещё нет (иначе docker compose up падает с
# "network ... declared as external, but could not be found").
# Запускать из корня проекта: ./scripts/ensure-external-networks.sh

set -e
for n in rkllama_default whisper_rknn_default; do
  if ! docker network inspect "$n" >/dev/null 2>&1; then
    echo "Creating docker network: $n"
    docker network create "$n"
  else
    echo "Network exists: $n"
  fi
done
echo "External networks OK."
