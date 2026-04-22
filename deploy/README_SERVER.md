# README SERVER

Se documentan los requerimientos de infraestructura para despliegue en servidor compartido.

## 1. Objetivo

Definir especificaciones para solicitar un servidor donde coexistiran dos sistemas (incluyendo Bank Reconciliation App) con operacion estable y acceso en red.

## 2. Especificaciones recomendadas de servidor

Se recomienda solicitar capacidad considerando servidor compartido con otro sistema.

### 2.1 Plataforma y sistema operativo

- Sistema operativo: Windows 10, Windows 11 o Windows Server 2016 en adelante.
- Arquitectura: 64-bit.
- Privilegios: cuenta con permisos para instalar dependencias y registrar servicio.

### 2.2 Capacidad minima y recomendada (servidor compartido)

- RAM: 8 GB recomendados (minimo 4 GB).
- Almacenamiento libre: 10 GB minimos para esta aplicacion.
- Recomendacion operativa: asignar espacio adicional para crecimiento de archivos historicos y respaldos.

### 2.3 Base de datos y coexistencia con otro sistema

- Base de datos requerida por el otro sistema: MariaDB (segun implementacion compartida).
- Bank Reconciliation App no requiere base de datos para su flujo principal.
- Se debe reservar capacidad para ambas aplicaciones sin saturar memoria/disco.
- Se debe separar puertos y rutas de servicio para evitar conflicto entre aplicaciones.

## 3. Consideraciones de red

- El servidor debe permanecer encendido para garantizar disponibilidad.
- Los equipos clientes deben estar en la misma red local o conectados por VPN.
- Se recomienda IP fija para evitar cambios de direccion de acceso.
- Debe permitirse comunicacion por el puerto configurado de cada sistema
  (por ejemplo, 2236 para el otro sistema y 8501 o el definido para esta app).
- Deben habilitarse reglas en firewall/antivirus para los puertos autorizados.

## 4. Requisitos de operacion y seguridad

- Gestion de servicios con inicio automatico al reiniciar el servidor.
- Monitoreo basico de CPU, RAM, disco y disponibilidad de puertos.
- Politica de respaldos para configuraciones, scripts y archivos operativos.
- Actualizaciones periodicas de seguridad del sistema operativo.
- Control de acceso administrativo y registro de eventos.

## 5. Texto sugerido para solicitud de infraestructura

Solicitud sugerida:

- Servidor compartido para dos sistemas en Windows Server 2016+ (o Windows 10/11),
  con 8 GB RAM recomendados, minimo 4 GB, y al menos 10 GB libres para Bank Reconciliation App
  (mas espacio adicional para historicos y respaldos).
- Red corporativa con IP fija, acceso por VPN/LAN y apertura de puertos autorizados en firewall/antivirus.
- Separacion de puertos/servicios entre ambas aplicaciones.
- Politica de disponibilidad permanente, monitoreo y respaldos.

Guia de implementacion recomendada para Windows compartido:

- Ver [deploy/WINDOWS_NSSM_SETUP.md](deploy/WINDOWS_NSSM_SETUP.md)

## 6. Instalacion base

Operacion ajustada para servidor compartido en Windows.

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.11 -e
```

## 7. Directorio de aplicacion y entorno

```powershell
New-Item -ItemType Directory -Path C:\apps\bank-reconciliation-app -Force
cd C:\apps
git clone https://github.com/DiegoEscobedo/bank-reconciliation-app.git
cd .\bank-reconciliation-app
py -3.11 -m venv .venv
py -3.11 -m venv .venv_clean
.\.venv_clean\Scripts\python.exe -m pip install --upgrade pip
.\.venv_clean\Scripts\python.exe -m pip install -r requirements.txt
```

## 8. Puerto y reglas de firewall

Separar puertos para evitar conflicto con el otro sistema.

- Puerto sugerido para Bank Reconciliation App: 8501 (o uno libre definido por infraestructura).
- Puerto del otro sistema: mantener el asignado por su equipo (ejemplo 2236).

```powershell
New-NetFirewallRule -DisplayName "BankReconciliation-8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -RemoteAddress 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 -Action Allow
```

Nota: ajustar `-RemoteAddress` a los rangos reales autorizados (LAN/VPN corporativa).

## 9. Registro como servicio de Windows

Se recomienda NSSM para ejecutar Streamlit como servicio.

1. Instalar NSSM (Non-Sucking Service Manager).
2. Crear servicio con los siguientes parametros:
3. Configurar el servicio para correr con cuenta dedicada de bajo privilegio
  (ejemplo: `svc_bankrec`), no con administrador local.

- Path: C:\apps\bank-reconciliation-app\.venv_clean\Scripts\python.exe
- Startup directory: C:\apps\bank-reconciliation-app
- Arguments: -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
- Service name sugerido: BankReconciliationApp

Comandos ejemplo:

```powershell
nssm install BankReconciliationApp "C:\apps\bank-reconciliation-app\.venv_clean\Scripts\python.exe" "-m streamlit run app.py --server.port 8501 --server.address 0.0.0.0"
nssm set BankReconciliationApp AppDirectory "C:\apps\bank-reconciliation-app"
nssm start BankReconciliationApp
```

Configuracion de cuenta de servicio (recomendado):

- No dejar contrasenas en comandos, scripts ni capturas.
- Configurar la cuenta del servicio desde `services.msc` (pestana **Log On**) o desde canal seguro autorizado por infraestructura.
- Rotar contrasena periodicamente y registrar evidencia de cambio.

Detalle completo de pasos y permisos:

- Ver [deploy/WINDOWS_NSSM_SETUP.md](deploy/WINDOWS_NSSM_SETUP.md)

## 10. Publicacion y acceso

- Opcion interna: acceso por IP fija y puerto (http://IP_SERVIDOR:8501).
- Opcion empresarial: publicar por reverse proxy corporativo (IIS/NGINX/ADC) con ruta o subdominio dedicado.
- No reutilizar puerto o ruta del otro sistema.

## 11. Operacion compartida con otro sistema

- Definir responsables por aplicacion (dueno tecnico y soporte).
- Mantener aislamiento de puertos, rutas, logs y respaldos.
- Coordinar ventanas de mantenimiento para no afectar ambos servicios.
- Validar consumo de RAM/CPU despues de liberar ambas aplicaciones en conjunto.

## 12. Actualizacion operativa

```powershell
cd C:\apps\bank-reconciliation-app
git pull origin main
.\.venv_clean\Scripts\python.exe -m pip install -r requirements.txt
.\.venv_clean\Scripts\python.exe -m pip check
Restart-Service BankReconciliationApp
```

## 13. Comandos de soporte

```powershell
Get-Service BankReconciliationApp
Restart-Service BankReconciliationApp
Get-NetTCPConnection -LocalPort 8501 -State Listen
Get-Process -Id (Get-NetTCPConnection -LocalPort 8501 -State Listen).OwningProcess
```

## 14. Alcance

Este esquema define operacion en servidor compartido Windows y no modifica el flujo local de desarrollo.

## 15. Checklist Go-Live (Intranet + VPN + ACL estrictas)

Usar este checklist antes de liberar a operacion.

### 15.1 Red y acceso

- [ ] 1. El servidor solo es accesible por red corporativa (LAN/VPN), sin publicacion directa a Internet.
- [ ] 2. La regla de firewall del puerto de la app limita origenes a subredes autorizadas (no Any).
- [ ] 3. Se validaron pruebas de acceso: permitido desde VPN corporativa y denegado desde red no autorizada.

### 15.2 Servicio y privilegios

- [ ] 4. El servicio corre con cuenta dedicada de bajo privilegio (no administrador local).
- [ ] 5. El servicio inicia automaticamente en reinicio del servidor.
- [ ] 6. Se confirmo que el servicio queda en Running y escucha en el puerto esperado.

### 15.3 Sistema de archivos y datos

- [ ] 7. La carpeta de aplicacion tiene permisos NTFS minimos (solo cuenta de servicio y admins).
- [ ] 8. Las carpetas de data y logs estan protegidas con el mismo criterio de minimo privilegio.
- [ ] 9. No se dejaron archivos de prueba con datos sensibles en rutas compartidas.

### 15.4 Configuracion operativa

- [ ] 10. El puerto de la app no colisiona con otros sistemas del mismo servidor.
- [ ] 11. Se definio nombre y responsable operativo del servicio (dueno tecnico + respaldo).
- [ ] 12. Se documento procedimiento de reinicio y recuperacion ante falla.

### 15.5 Logging, respaldo y mantenimiento

- [ ] 13. Logs habilitados y verificados, sin exponer informacion sensible innecesaria.
- [ ] 14. Respaldo diario configurado para scripts, configuracion y salida operativa critica.
- [ ] 15. Se realizo prueba de restauracion (archivo o carpeta) con evidencia.

### 15.6 Criterio de salida

Go-Live aprobado cuando:

- Los 15 puntos estan en cumplimiento.
- Existe evidencia minima (capturas o bitacora tecnica) de los puntos 2, 3, 6, 14 y 15.
