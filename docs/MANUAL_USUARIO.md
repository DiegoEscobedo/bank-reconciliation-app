# Manual de Usuario

Se describen los pasos operativos para ejecutar conciliaciones y obtener los archivos de salida.

## 1. Requisitos previos

- Entorno Python operativo.
- Dependencias instaladas desde requirements.txt.
- Archivos del periodo a conciliar.

## 2. Inicio de aplicacion

```powershell
streamlit run app.py
```

Acceso local: http://localhost:8501

## 3. Flujo principal

En barra lateral se cargan:
1. Archivo JDE.
2. Archivo(s) bancario(s).
3. Reporte Caja (opcional).
4. Conciliacion anterior (opcional).
5. Tolerancias (opcional).

Posteriormente se ejecuta accion Conciliar.

## 4. Validacion de agrupaciones

Cuando existan propuestas:
- Se revisan monto, fecha, tienda y descripcion.
- Se aceptan o rechazan grupos segun criterio operativo.

## 5. Resultados visibles

- Resumen de conciliacion.
- Matches exactos, agrupados e inversos.
- Pendientes de banco y JDE.
- Diagnostico de no conciliacion.
- Analisis historico (si fue cargado).

## 6. Descargas

Se habilitan segun el caso:
- Excel de conciliacion.
- Papel de Trabajo actualizado.

## 7. Modo Marcar por batch

Flujo independiente:
1. Cambio de modo en sidebar.
2. Carga de Papel de Trabajo.
3. Captura de batches.
4. Previsualizacion y confirmacion de grupos.
5. Generacion de descargable final.

## 8. Incidencias comunes

### Boton de conciliacion deshabilitado
Verificar carga de JDE y al menos un archivo bancario.

### Movimiento no conciliado esperado
Verificar cuenta, tienda, tipo, fecha, monto y posible uso previo en otra agrupacion.

### Aplicacion sin respuesta en navegador
Verificar que Streamlit este activo y puerto 8501 disponible.
