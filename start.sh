#!/bin/bash
# Inicia a stats-api do orquestrador e o nginx
set -e

export SERVER_ID="${SERVER_ID:-MTLADVL088}"
export MAPA_PATH="/app/orquestrador/mapa.yaml"

echo "SERVER_ID: $SERVER_ID"
echo "MAPA_PATH: $MAPA_PATH"

# Garante que a API usa o mapa.yaml do repo montado
export REPO_PATH=""

pkill -f "uvicorn server:app" 2>/dev/null || true
sleep 1

cd /app/orquestrador/api
SERVER_ID="$SERVER_ID" uvicorn server:app --host 0.0.0.0 --port 8900 &
API_PID=$!
echo "API PID: $API_PID"

nginx -s reload 2>/dev/null || nginx

echo "Orquestrador rodando:"
echo "  Frontend: http://0.0.0.0:3310"
echo "  API:      http://0.0.0.0:8900"
