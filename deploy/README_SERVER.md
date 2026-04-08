# Deploy en Servidor Propio (Ubuntu + Nginx + systemd)

Este setup no rompe tu flujo local

streamlit run app.py

## 1) Preparar servidor

sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx git

sudo useradd -m -s /bin/bash appuser || true
sudo mkdir -p /opt/bank-reconciliation-app
sudo chown -R appuser:appuser /opt/bank-reconciliation-app

## 2) Clonar app y entorno virtual

sudo -u appuser bash -lc '
cd /opt
if [ ! -d bank-reconciliation-app/.git ]; then
  git clone https://github.com/DiegoEscobedo/bank-reconciliation-app.git bank-reconciliation-app
fi
cd bank-reconciliation-app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
'

## 3) Logs

sudo mkdir -p /var/log/bank-reconciliation
sudo chown -R appuser:appuser /var/log/bank-reconciliation

## 4) Activar servicio systemd

sudo cp deploy/systemd/bank-reconciliation.service /etc/systemd/system/

# Ajusta User, Group, WorkingDirectory y PATH si cambiaste rutas
sudo systemctl daemon-reload
sudo systemctl enable bank-reconciliation
sudo systemctl start bank-reconciliation
sudo systemctl status bank-reconciliation --no-pager

## 5) Configurar Nginx

sudo cp deploy/nginx/bank-reconciliation.conf /etc/nginx/sites-available/bank-reconciliation
sudo ln -sf /etc/nginx/sites-available/bank-reconciliation /etc/nginx/sites-enabled/bank-reconciliation

# Cambia server_name en el archivo por tu dominio real
sudo nginx -t
sudo systemctl reload nginx

## 6) SSL con Let's Encrypt

sudo certbot --nginx -d conciliacion.tu-dominio.com

## 7) Deploy futuro

chmod +x deploy/scripts/deploy.sh
./deploy/scripts/deploy.sh

## Notas de operación

- Streamlit queda interno en 127.0.0.1:8501.
- El acceso público entra por Nginx (80/443).
- Tu entorno local no se afecta, porque esto corre en otro servidor.
