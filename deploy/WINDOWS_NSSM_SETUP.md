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
- Definir cuenta de servicio dedicada (ejemplo: `svc_bankrec`) para ejecutar la app.

## 3. Estructura recomendada

- Ruta del proyecto: `C:\apps\bank-reconciliation-app`
- Ruta de NSSM: `C:\tools\nssm\nssm.exe`
- Nombre de servicio: `BankReconciliationApp`

## 4. Instalacion base de aplicacion

El despliegue y la ejecucion del servicio usan exclusivamente `.venv_clean`.

Ejecutar en PowerShell con permisos de administrador:

```powershell
New-Item -ItemType Directory -Path C:\apps -Force
Set-Location C:\apps

git clone https://github.com/DiegoEscobedo/bank-reconciliation-app.git
Set-Location C:\apps\bank-reconciliation-app

py -3.11 -m venv .venv_clean
.\.venv_clean\Scripts\python.exe -m pip install --upgrade pip
.\.venv_clean\Scripts\python.exe -m pip install -r requirements.txt
```

### 4.1 Cuenta de servicio de bajo privilegio (recomendado)

Despues de la instalacion base, crear un usuario dedicado para ejecutar el servicio.

```powershell
$SvcUser = "svc_bankrec"
$SvcPass = Read-Host "Password para $SvcUser" -AsSecureString

if (-not (Get-LocalUser -Name $SvcUser -ErrorAction SilentlyContinue)) {
  New-LocalUser -Name $SvcUser -Password $SvcPass -AccountNeverExpires
}

# Mantenerlo como usuario estandar (sin privilegios de administrador)
Add-LocalGroupMember -Group "Users" -Member $SvcUser -ErrorAction SilentlyContinue
```

Asignar permisos minimos sobre la carpeta de la app (lectura/escritura/ejecucion para operar logs y archivos temporales):

```powershell
icacls "C:\apps\bank-reconciliation-app" /grant "${SvcUser}:(OI)(CI)M" /T
```

Conceder derecho **Log on as a service** al usuario `svc_bankrec`:

- Opcion GUI: `secpol.msc` -> Local Policies -> User Rights Assignment -> Log on as a service.
- Agregar el usuario `svc_bankrec` y aplicar politicas.

## 5. Prueba manual antes del servicio

Validar primero que la app corre correctamente:

```powershell
Set-Location C:\apps\bank-reconciliation-app
.\.venv_clean\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
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

### 7.1 Crear script de arranque (start_service.bat)

Crear el archivo `C:\apps\bank-reconciliation-app\start_service.bat`:

```powershell
@"
@echo off
set APP_DIR=C:\apps\bank-reconciliation-app
set PY=%APP_DIR%\.venv_clean\Scripts\python.exe
cd /d %APP_DIR%
"%PY%" -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --browser.gatherUsageStats false
"@ | Set-Content -Encoding ASCII C:\apps\bank-reconciliation-app\start_service.bat
```

### 7.2 Crear servicio (NSSM ejecuta BAT)

```powershell
C:\tools\nssm\nssm.exe install BankReconciliationApp C:\Windows\System32\cmd.exe "/c C:\apps\bank-reconciliation-app\start_service.bat"
```

### 7.3 Configurar directorio de trabajo

```powershell
C:\tools\nssm\nssm.exe set BankReconciliationApp AppDirectory "C:\apps\bank-reconciliation-app"
```

### 7.4 Configurar inicio automatico

```powershell
C:\tools\nssm\nssm.exe set BankReconciliationApp Start SERVICE_AUTO_START
```

### 7.5 Configurar cuenta de servicio en NSSM

Registrar el servicio para que corra con la cuenta dedicada (no administrador local).

Recomendacion de seguridad:

- Evitar contrasenas en linea de comandos, scripts o capturas de pantalla.
- Configurar usuario y contrasena del servicio desde `services.msc` -> servicio `BankReconciliationApp` -> pestana **Log On**.
- Rotar contrasena de `svc_bankrec` segun politica corporativa y conservar evidencia operativa.

## 8. Logs recomendados

```powershell
New-Item -ItemType Directory -Path C:\apps\bank-reconciliation-app\logs -Force

C:\tools\nssm\nssm.exe set BankReconciliationApp AppStdout "C:\apps\bank-reconciliation-app\logs\service_out.log"
C:\tools\nssm\nssm.exe set BankReconciliationApp AppStderr "C:\apps\bank-reconciliation-app\logs\service_err.log"
```

## 9. Firewall y red

Abrir el puerto asignado (ejemplo 8501):

```powershell
New-NetFirewallRule -DisplayName "BankReconciliation-8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -RemoteAddress 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 -Action Allow
```

Nota: cambiar `-RemoteAddress` por las subredes autorizadas de LAN/VPN corporativa.

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
.\.venv_clean\Scripts\python.exe -m pip install -r requirements.txt
.\.venv_clean\Scripts\python.exe -m pip check
Restart-Service BankReconciliationApp
```

## 13. Troubleshooting rapido

### Servicio en estado Stopped

- Revisar logs:
  - `C:\apps\bank-reconciliation-app\logs\service_out.log`
  - `C:\apps\bank-reconciliation-app\logs\service_err.log`
- Confirmar que existe Python en:
  - `C:\apps\bank-reconciliation-app\.venv_clean\Scripts\python.exe`

### Puerto no disponible

```powershell
Get-NetTCPConnection -LocalPort 8501 -State Listen
```

Si esta ocupado por otro proceso, cambiar puerto en el servicio NSSM.

### Dependencias faltantes

```powershell
Set-Location C:\apps\bank-reconciliation-app
.\.venv_clean\Scripts\python.exe -m pip install -r requirements.txt
Restart-Service BankReconciliationApp
```

### Recuperacion rapida de configuracion NSSM

Si el servicio presenta errores de ruta/comando (por ejemplo, ejecucion de `python` incorrecta),
usar este bloque en PowerShell como administrador para recrear la configuracion limpia:

```powershell
# 1) Variables
$N   = "C:\tools\nssm\nssm.exe"
$S   = "BankReconciliationApp"
$APP = "C:\apps\bank-reconciliation-app"
$BAT = "$APP\start_service.bat"

# 2) Validaciones rapidas
if (!(Test-Path $N))  { throw "No existe NSSM en: $N" }

# 3) Crear/actualizar start_service.bat
@"
@echo off
set APP_DIR=C:\apps\bank-reconciliation-app
set PY=%APP_DIR%\.venv_clean\Scripts\python.exe
cd /d %APP_DIR%
"%PY%" -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --browser.gatherUsageStats false
"@ | Set-Content -Encoding ASCII $BAT

# 4) Preparar carpeta de logs
New-Item -ItemType Directory -Path "$APP\logs" -Force | Out-Null

# 5) Detener y eliminar servicio anterior (si existe)
& $N stop $S 2>$null
& $N remove $S confirm 2>$null

# 6) Crear servicio correcto (via BAT)
& $N install $S "C:\Windows\System32\cmd.exe" "/c $BAT"

# 7) Configuracion del servicio
& $N set $S AppDirectory $APP
& $N set $S Start SERVICE_AUTO_START
& $N set $S AppStdout "$APP\logs\service_out.log"
& $N set $S AppStderr "$APP\logs\service_err.log"

# 8) Iniciar servicio
& $N start $S

# 9) Validar estado y puerto
Get-Service $S
Get-NetTCPConnection -LocalPort 8501 -State Listen

# 10) Ver logs (ultimas lineas)
Get-Content "$APP\logs\service_err.log" -Tail 80
Get-Content "$APP\logs\service_out.log" -Tail 80
```

## 14. Checklist de cierre

- Servicio creado y en `Running`.
- Servicio ejecutando con cuenta dedicada de bajo privilegio (ej. `svc_bankrec`).
- Puerto accesible desde red autorizada.
- Firewall aplicado para el puerto de la app.
- Logs de salida y error configurados.
- Inicio automatico validado en reinicio del servidor.
- Separacion de puertos confirmada respecto al otro sistema.
