#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRET_FILE="/app/secrets/dbpiske.env"

if [ ! -f "$SECRET_FILE" ]; then
  echo "Arquivo de secrets não encontrado: $SECRET_FILE"
  exit 1
fi

. "$SECRET_FILE"

TOKEN="${GHTOKEN:-${GITHUB_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  echo "Token não encontrado em $SECRET_FILE (esperado: GHTOKEN ou GITHUB_TOKEN)"
  exit 1
fi

REMOTE=$(git -C "$SCRIPT_DIR" remote get-url origin)
PUSH_URL="https://x-access-token:${TOKEN}@${REMOTE#https://}"

BRANCH="${1:-$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD)}"
git -C "$SCRIPT_DIR" push "$PUSH_URL" "$BRANCH"
echo "Push de '$BRANCH' concluído."
