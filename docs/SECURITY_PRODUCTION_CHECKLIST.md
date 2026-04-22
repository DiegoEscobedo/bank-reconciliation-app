# Checklist de Seguridad para Produccion

Este checklist sirve como evidencia minima para liberar la aplicacion a produccion.

## 1. Red y exposicion

- [ ] La app no esta publicada directamente a Internet.
- [ ] El acceso solo esta permitido por LAN/VPN corporativa.
- [ ] El puerto de la app (ej. 8501) tiene regla de firewall con `RemoteAddress` restringido.
- [ ] Se realizo prueba positiva (red autorizada) y negativa (red no autorizada).

Evidencia sugerida:
- Captura de `Get-NetFirewallRule` y `Get-NetFirewallAddressFilter`.
- Bitacora de prueba de acceso permitido/denegado.

## 2. Servicio y privilegios

- [ ] El servicio corre con cuenta dedicada de bajo privilegio (no administrador local).
- [ ] El usuario de servicio tiene solo permisos NTFS minimos en carpetas de app/data/logs.
- [ ] El servicio inicia automaticamente al reiniciar servidor.

Evidencia sugerida:
- Captura de `services.msc` (pestana Log On y Startup type).
- Salida de `icacls` para carpeta de aplicacion.

## 3. Credenciales y secretos

- [ ] No hay contrasenas en scripts, README, historial de terminal ni capturas.
- [ ] Las credenciales operativas se gestionan en mecanismo seguro corporativo.
- [ ] Existe politica de rotacion y responsable asignado.

Evidencia sugerida:
- Procedimiento documentado de custodia/rotacion.
- Registro de ultima rotacion.

## 4. Aplicacion

- [ ] Los errores mostrados al usuario no exponen stack trace ni rutas internas.
- [ ] Los nombres de archivos subidos se sanitizan antes de guardarse temporalmente.
- [ ] Se valida tamano y extension de archivos de entrada (segun politica interna).

Evidencia sugerida:
- Prueba funcional de error controlado.
- Captura de carga con nombre de archivo especial (espacios/simbolos).

## 5. Logging y monitoreo

- [ ] El nivel de log en produccion es INFO (o el definido por seguridad).
- [ ] Logs con rotacion habilitada para evitar crecimiento ilimitado.
- [ ] No se registran datos sensibles innecesarios en texto plano.

Evidencia sugerida:
- Archivo de configuracion de logs.
- Muestra de logs redaccionados.

## 6. Dependencias y parchado

- [ ] Dependencias con versiones controladas (pinning o lockfile).
- [ ] `requirements.txt` sincronizado desde entorno validado y aplicado en `.venv_clean` de produccion.
- [ ] Escaneo de vulnerabilidades ejecutado antes de liberar.
- [ ] Plan de actualizacion de parches definido (mensual/trimestral).

Evidencia sugerida:
- Reporte de escaneo (`pip-audit` u herramienta corporativa).
- Evidencia de integridad (`pip check`) en el entorno productivo.
- Documento de ventana de mantenimiento.

## 7. Respaldo y recuperacion

- [ ] Respaldo diario de configuracion, scripts y datos operativos criticos.
- [ ] Restauracion probada (al menos 1 simulacro documentado).
- [ ] Objetivo RTO/RPO definido con operaciones.

Evidencia sugerida:
- Registro de job de respaldo.
- Bitacora de prueba de restauracion.

## 8. Criterio de Go-Live

Go-Live aprobado cuando:

- Todos los puntos criticos (Red, Servicio, Credenciales, Respaldo) estan en cumplimiento.
- Existe evidencia tecnica minima adjunta.
- Se designa responsable operativo y de soporte.
