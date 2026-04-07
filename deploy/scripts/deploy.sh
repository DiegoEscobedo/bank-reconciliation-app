#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/bank-reconciliation-app"
SERVICE_NAME="bank-reconciliation"

if [ ! -d "$APP_DIR" ]; then
  echo "No existe $APP_DIR"
  exit 1
fi

cd "$APP_DIR"

echo "[1/4] Actualizando codigo"
git pull origin main

echo "[2/4] Instalando dependencias"
.venv/bin/pip install -r requirements.txt

echo "[3/4] Reiniciando servicio"
sudo systemctl restart "$SERVICE_NAME"

echo "[4/4] Verificando estado"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "Deploy terminado"
