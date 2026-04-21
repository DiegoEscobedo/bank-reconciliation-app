# Manual de Usuario (version simple)
Objetivo: ayudar a conciliar movimientos de banco contra JDE y descargar tu resultado sin complicaciones.

## 1. Que hace esta aplicacion

La aplicacion compara dos fuentes:

- Banco: los movimientos que vienen en tu estado de cuenta.
- JDE: los movimientos contables del sistema interno.

Despues de comparar, te muestra:

- Lo que ya coincide.
- Lo que necesita revision.
- Lo que quedo pendiente.

Al final puedes descargar un archivo Excel con el resultado.

## 2. Antes de empezar

Necesitas lo siguiente:

- Archivo JDE del periodo a revisar.
- Uno o varios archivos de banco del mismo periodo segun sean requeridos.
- (Opcional) Reporte de caja.
- (Opcional) Conciliacion anterior.

Recomendaciones simples:

- Trabaja primero con un solo periodo (por ejemplo, una semana o un mes).
- No cambies nombres de columnas en los archivos originales.
- Guarda una copia de seguridad de tus archivos antes de iniciar.

## 3. Abrir la aplicacion

Si tu equipo de sistemas ya la dejo instalada en servidor, solo abre el enlace que te compartieron.

Ejemplo:

- http://IP_SERVIDOR:8501

Si la usas de forma local en tu PC:

```powershell
streamlit run app.py
```

Luego abre en navegador:

- http://localhost:8501

## 4. Recorrido rapido (en 7 pasos)

### Paso 1. Cargar el archivo JDE

En la barra lateral, busca el campo de JDE y selecciona tu archivo.

### Paso 2. Cargar archivo(s) bancario(s)

Selecciona uno o varios archivos de banco.

Consejo: si tienes varios bancos, cargalos todos para tener un resultado completo.

### Paso 3. Cargar archivos opcionales (si aplica)

- Reporte Caja.
- Conciliacion anterior.

Si no los tienes, puedes continuar sin problema.

### Paso 4. Revisar tolerancias (solo si te lo pidieron)

Si no sabes que valor usar, deja las tolerancias por defecto.

### Paso 5. Ejecutar conciliacion

Haz clic en el boton de conciliar.

La aplicacion procesa la informacion y genera propuestas.

### Paso 6. Revisar propuestas agrupadas

Cuando aparezcan grupos propuestos, valida:

- Monto total.
- Fecha.
- Descripcion.
- Logica del grupo.

Si un grupo tiene sentido, aceptalo. Si no, rechaza.

### Paso 7. Descargar resultado final

Descarga los archivos habilitados en pantalla:

- Excel de conciliacion.
- Papel de Trabajo actualizado (cuando aplique).

## 5. Como leer los resultados

### Coincidencias exactas

Un movimiento banco coincide con un movimiento JDE.

### Coincidencias agrupadas

Un movimiento se empata contra varios del otro lado.

### Pendientes

Movimientos que no encontraron pareja valida y requieren revision manual.

### Diagnostico

Pistas de por que algo no concilio (por ejemplo fecha, tipo, cuenta, tienda o monto).

## 6. Modo Marcar por batch (flujo aparte)

Este modo sirve para marcar grupos por lote en Papel de Trabajo.

Pasos:

1. Cambia al modo Marcar por batch en la barra lateral.
2. Carga el Papel de Trabajo.
3. Captura batches.
4. Revisa previsualizacion y confirma.
5. Descarga el archivo final.

## 7. Errores comunes y solucion rapida

### No se activa el boton de conciliar

Revisa que hayas cargado:

- 1 archivo JDE.
- Al menos 1 archivo bancario.

### Esperaba una conciliacion y no paso

Revisa en este orden:

1. Cuenta correcta.
2. Fecha dentro del rango esperado.
3. Tipo de movimiento (deposito/retiro/comision).
4. Monto correcto.
5. Que el movimiento no se haya usado en otro grupo.

### La pagina no abre o no responde

Revisa:

1. Que la app este encendida.
2. Que el puerto (normalmente 8501) este disponible.
3. Que tengas acceso de red/VPN si esta en servidor.

### El archivo descargado no aparece

Revisa la carpeta de Descargas de tu navegador y vuelve a intentar.

## 8. Buenas practicas para evitar retrabajo

- Concilia por periodos cortos y constantes.
- No mezcles periodos en una misma corrida.
- Guarda los resultados con nombre y fecha.
- Si tienes dudas en una agrupacion, no la apruebes hasta validar con evidencia.

## 9. Checklist corto de cierre

Antes de terminar, confirma:

1. Revise resumen general.
2. Revise agrupaciones propuestas.
3. Revise pendientes.
4. Descargue archivo final.
5. Guarde evidencia del proceso.

## 10. Glosario sencillo

- Conciliar: hacer que banco y JDE coincidan con reglas validas.
- JDE: archivo de movimientos contables internos.
- Pendiente: movimiento sin pareja confirmada.
- Agrupacion: varios movimientos que juntos equivalen a uno.
- Tolerancia: margen permitido en fecha o monto.

---

Si es tu primera vez, usa este orden:

1. Cargar archivos.
2. Conciliar.
3. Revisar agrupaciones.
4. Descargar resultado.

Con eso ya puedes operar el flujo principal sin conocimientos tecnicos.
