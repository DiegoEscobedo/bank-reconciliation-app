# Manual de Usuario - Conciliacion Bancaria

## 1. Objetivo
Este manual explica como usar la aplicacion de conciliacion bancaria para:
- Cargar archivos bancarios y JDE.
- Revisar agrupaciones propuestas.
- Generar y descargar el reporte final de conciliacion.

## 2. Requisitos
- Windows con Python instalado.
- Dependencias del proyecto instaladas.
- Acceso a los archivos de entrada:
  - Banco (CSV/XLSX)
  - JDE (CSV o Papel de Trabajo XLSX)
  - Reporte Caja (opcional)
  - Conciliacion anterior (opcional)

## 3. Iniciar la aplicacion
En la carpeta del proyecto ejecutar:

```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8502
```

Abrir en navegador:
- Local: http://localhost:8502
- Red local: http://<IP_DEL_EQUIPO>:8502

## 4. Pantalla principal
La barra lateral tiene 4 cargas:

1. Archivo JDE
- Cuentas 6614 y 7133 (BBVA): subir Papel de Trabajo (.xlsx).
- Otras cuentas: subir Auxiliar de Contabilidad del JDE (.csv).

2. Archivos bancarios
- Se pueden subir uno o varios estados de cuenta.
- Soporta BBVA, Banorte, HSBC, Scotiabank, NetPay y Mercado Pago.

3. Reporte Caja (opcional)
- Sirve para enriquecer tienda y forma de pago.
- El enriquecimiento es controlado por reglas internas del pipeline.

4. Conciliacion anterior (opcional)
- Permite identificar pendientes historicos ya resueltos.

## 5. Flujo de uso paso a paso
1. Subir JDE.
2. Subir archivos bancarios.
3. (Opcional) Subir Reporte Caja.
4. (Opcional) Subir conciliacion anterior.
5. Presionar Conciliar.
6. Revisar la fase de validacion de agrupaciones.
7. Aceptar o rechazar propuestas.
8. Finalizar y descargar el Excel resultado.

## 6. Interpretacion de resultados
El reporte final separa resultados en:
- Matches exactos.
- Matches agrupados.
- Agrupados inversos.
- Pendientes banco.
- Pendientes JDE.

Indicadores clave:
- Mientras mas matches exactos, mejor calidad de conciliacion automatica.
- Pendientes altos suelen indicar diferencias de fecha, cuenta, descripcion o clasificacion.

## 7. Reglas operativas importantes
- El matching exacto considera monto, fecha y filtros de negocio.
- En agrupaciones se aplican reglas de control para reducir falsos positivos.
- El enriquecimiento desde Reporte Caja trabaja con logica 1 a 1 (un movimiento no se reutiliza) y control por fecha/monto.

## 8. Buenas practicas
- Verificar que los archivos correspondan al mismo periodo.
- Evitar editar manualmente formatos de fecha y monto antes de cargar.
- Subir todos los archivos bancarios del periodo en una sola corrida.
- Revisar agrupaciones con monto grande o con fechas antiguas antes de aceptar.

## 9. Solucion de problemas
### 9.1 El boton Conciliar no se habilita
Falta cargar JDE o al menos un archivo bancario.

### 9.2 La app no abre
- Verificar que Streamlit este corriendo.
- Verificar que el puerto 8502 no este ocupado.

### 9.3 Un movimiento esperado no concilia
Revisar:
- Cuenta bancaria (larga/corta).
- Fecha del movimiento.
- Monto y signo (+/-).
- Tienda y tipo de pago.
- Si el registro ya fue consumido por una agrupacion previa.

### 9.4 No aparecen tienda o forma de pago en algunos movimientos
- Confirmar que exista movimiento equivalente en Reporte Caja.
- Confirmar que la fecha y el monto sean compatibles con las reglas de enriquecimiento.

## 10. Salida del proceso
La app genera un archivo Excel de conciliacion en la carpeta temporal de ejecucion y lo deja disponible para descarga desde la interfaz.

## 11. Recomendacion de cierre
Al terminar:
- Guardar el Excel final con nombre de periodo.
- Registrar observaciones de pendientes para el siguiente corte.
- Reutilizar el archivo de conciliacion como historico en la siguiente corrida.
