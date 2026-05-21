#!/bin/bash
# Faz push usando GITHUB_TOKEN de /app/secrets/${USER}.env, sem persistir
# credencial no remote. Override do user via GH_USER=outro ./push.sh.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GH_USER="${GH_USER:-${SUDO_USER:-$(whoami)}}"
SECRET_FILE="/app/secrets/${GH_USER}.env"

if [ ! -f "$SECRET_FILE" ]; then
  echo "Arquivo de secrets não encontrado: $SECRET_FILE"
  echo "Crie com: sudo install -m 600 /dev/stdin $SECRET_FILE <<< 'GITHUB_TOKEN=ghp_xxx'"
  exit 1
fi

# shellcheck disable=SC1090
. "$SECRET_FILE"

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "GITHUB_TOKEN não definido em $SECRET_FILE"
  exit 1
fi

REMOTE=$(git -C "$SCRIPT_DIR" remote get-url origin)
case "$REMOTE" in
  https://github.com/*)
    PUSH_URL="https://x-access-token:${GITHUB_TOKEN}@${REMOTE#https://}"
    ;;
  *)
    echo "remote origin não é HTTPS do github: $REMOTE"
    exit 1
    ;;
esac

BRANCH="${1:-$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref HEAD)}"
git -C "$SCRIPT_DIR" push "$PUSH_URL" "$BRANCH"
echo "Push de $BRANCH concluído (user: $GH_USER)."
