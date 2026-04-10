# README SERVER

Se documenta el procedimiento de despliegue en Ubuntu con systemd y Nginx.

## 1. Objetivo

Publicar la aplicacion como servicio estable con acceso por dominio y HTTPS.

## 2. Instalacion base

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx git
```

## 3. Usuario de servicio y directorio

```bash
sudo useradd -m -s /bin/bash appuser || true
sudo mkdir -p /opt/bank-reconciliation-app
sudo chown -R appuser:appuser /opt/bank-reconciliation-app
```

## 4. Clonado e instalacion de aplicacion

```bash
sudo -u appuser bash -lc '
cd /opt
if [ ! -d bank-reconciliation-app/.git ]; then
  git clone https://github.com/DiegoEscobedo/bank-reconciliation-app.git bank-reconciliation-app
fi
cd bank-reconciliation-app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
'
```

## 5. Servicio systemd

```bash
sudo cp deploy/systemd/bank-reconciliation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bank-reconciliation
sudo systemctl start bank-reconciliation
sudo systemctl status bank-reconciliation --no-pager
```

## 6. Publicacion con Nginx

```bash
sudo cp deploy/nginx/bank-reconciliation.conf /etc/nginx/sites-available/bank-reconciliation
sudo ln -sf /etc/nginx/sites-available/bank-reconciliation /etc/nginx/sites-enabled/bank-reconciliation
sudo nginx -t
sudo systemctl reload nginx
```

Debe configurarse server_name con el dominio correspondiente.

## 7. Certificado SSL

```bash
sudo certbot --nginx -d conciliacion.tu-dominio.com
```

## 8. Actualizacion operativa

```bash
chmod +x deploy/scripts/deploy.sh
./deploy/scripts/deploy.sh
```

## 9. Comandos de soporte

```bash
sudo systemctl restart bank-reconciliation
sudo systemctl status bank-reconciliation
journalctl -u bank-reconciliation -f
sudo tail -f /var/log/nginx/error.log
```

## 10. Alcance

Este esquema de despliegue no modifica el flujo local de desarrollo.
