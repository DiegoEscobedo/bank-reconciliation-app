# Configuracion de Servicio en Windows con NSSM

Este documento describe como publicar Bank Reconciliation App como servicio de Windows
usando NSSM (Non-Sucking Service Manager), en un servidor compartido.

## 1. Objetivo

Dejar la aplicacion ejecutandose como servicio para que:

- Inicie automaticamente al reiniciar el servidor.
- No dependa de una consola abierta.
- Se administre con comandos de servicio (start, stop, restart).

## 2. Prerrequisitos

- Sistema operativo: Windows 10, 11 o Windows Server 2016+.
- Permisos de administrador local.
- Git instalado.
- Python 3.11 instalado.
- Puerto asignado para la app (recomendado: 8501, o el que autorice infraestructura).

## 3. Estructura recomendada

- Ruta del proyecto: `C:\apps\bank-reconciliation-app`
- Ruta de NSSM: `C:\tools\nssm\nssm.exe`
- Nombre de servicio: `BankReconciliationApp`

## 4. Instalacion base de aplicacion

Ejecutar en PowerShell con permisos de administrador:

```powershell
New-Item -ItemType Directory -Path C:\apps -Force
Set-Location C:\apps

git clone https://github.com/DiegoEscobedo/bank-reconciliation-app.git
Set-Location C:\apps\bank-reconciliation-app

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 5. Prueba manual antes del servicio

Validar primero que la app corre correctamente:

```powershell
Set-Location C:\apps\bank-reconciliation-app
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

Verificar acceso:

- Local: `http://localhost:8501`
- Red: `http://IP_SERVIDOR:8501`

Detener con `Ctrl+C` y continuar.

## 6. Instalacion de NSSM

1. Descargar NSSM desde su sitio oficial.
2. Descomprimir y copiar `nssm.exe` a: `C:\tools\nssm\nssm.exe`
3. Validar:

```powershell
C:\tools\nssm\nssm.exe version
```

## 7. Registro del servicio

### 7.1 Crear servicio

```powershell
C:\tools\nssm\nssm.exe install BankReconciliationApp "C:\apps\bank-reconciliation-app\.venv\Scripts\python.exe" "-m streamlit run app.py --server.port 8501 --server.address 0.0.0.0"
```

### 7.2 Configurar directorio de trabajo

```powershell
C:\tools\nssm\nssm.exe set BankReconciliationApp AppDirectory "C:\apps\bank-reconciliation-app"
```

### 7.3 Configurar inicio automatico

```powershell
C:\tools\nssm\nssm.exe set BankReconciliationApp Start SERVICE_AUTO_START
```

## 8. Logs recomendados

```powershell
New-Item -ItemType Directory -Path C:\apps\bank-reconciliation-app\logs -Force

C:\tools\nssm\nssm.exe set BankReconciliationApp AppStdout "C:\apps\bank-reconciliation-app\logs\service_out.log"
C:\tools\nssm\nssm.exe set BankReconciliationApp AppStderr "C:\apps\bank-reconciliation-app\logs\service_err.log"
```

## 9. Firewall y red

Abrir el puerto asignado (ejemplo 8501):

```powershell
New-NetFirewallRule -DisplayName "BankReconciliation-8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow
```

Notas de convivencia en servidor compartido:

- No reutilizar puertos del otro sistema (ej. 2236).
- Usar IP fija del servidor.
- Mantener reglas de firewall separadas por aplicacion.

## 10. Arranque y validacion

### 10.1 Iniciar servicio

```powershell
C:\tools\nssm\nssm.exe start BankReconciliationApp
```

### 10.2 Verificar estado

```powershell
Get-Service BankReconciliationApp
Get-NetTCPConnection -LocalPort 8501 -State Listen
```

### 10.3 Reiniciar servicio

```powershell
Restart-Service BankReconciliationApp
```

## 11. Operacion diaria

- Iniciar: `Start-Service BankReconciliationApp`
- Detener: `Stop-Service BankReconciliationApp`
- Reiniciar: `Restart-Service BankReconciliationApp`
- Estado: `Get-Service BankReconciliationApp`

## 12. Actualizacion de aplicacion

```powershell
Set-Location C:\apps\bank-reconciliation-app

git pull origin main
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Restart-Service BankReconciliationApp
```

## 13. Troubleshooting rapido

### Servicio en estado Stopped

- Revisar logs:
  - `C:\apps\bank-reconciliation-app\logs\service_out.log`
  - `C:\apps\bank-reconciliation-app\logs\service_err.log`
- Confirmar que existe Python en:
  - `C:\apps\bank-reconciliation-app\.venv\Scripts\python.exe`

### Puerto no disponible

```powershell
Get-NetTCPConnection -LocalPort 8501 -State Listen
```

Si esta ocupado por otro proceso, cambiar puerto en el servicio NSSM.

### Dependencias faltantes

```powershell
Set-Location C:\apps\bank-reconciliation-app
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Restart-Service BankReconciliationApp
```

## 14. Checklist de cierre

- Servicio creado y en `Running`.
- Puerto accesible desde red autorizada.
- Firewall aplicado para el puerto de la app.
- Logs de salida y error configurados.
- Inicio automatico validado en reinicio del servidor.
- Separacion de puertos confirmada respecto al otro sistema.
