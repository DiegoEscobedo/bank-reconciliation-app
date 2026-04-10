# SRS - Especificacion de Requisitos de Software

Version: 2.2  
Fecha: 10/04/2026  
Autor: Diego Escobedo

## 1. Proposito

Se especifican los requisitos funcionales y no funcionales del Sistema de Conciliacion Bancaria para su operacion, mantenimiento y evolucion controlada.

## 2. Alcance

El sistema cubre:
- Carga de archivos bancarios y JDE.
- Conciliacion exacta, agrupada y agrupada inversa.
- Validacion interactiva de propuestas.
- Generacion de reporte final en Excel.
- Write-back de Papel de Trabajo para cuentas habilitadas.
- Marcado independiente por batch.
- Analisis historico de pendientes.

## 3. Actores

- Analista contable: operacion y validacion de resultados.
- Administrador tecnico: mantenimiento y despliegue.

## 4. Requisitos funcionales

### RF-01 Carga de archivos
- Debe permitirse carga de banco en csv, xlsx o xls.
- Debe permitirse carga de JDE en CSV o Papel de Trabajo Excel.
- Debe permitirse carga opcional de Reporte Caja y conciliacion anterior.

### RF-02 Deteccion de formato
- Debe detectarse automaticamente el parser aplicable.
- Debe mostrarse error descriptivo cuando el formato no sea valido.

### RF-03 Normalizacion
- Debe transformarse toda fuente al esquema interno estandar.
- Deben estandarizarse cuenta, fecha, descripcion, montos y tipo.

### RF-04 Validacion
- Debe validarse estructura y tipos antes del matching.
- Debe detenerse el flujo cuando exista incumplimiento de esquema.

### RF-05 Matching exacto
- Debe ejecutarse conciliacion 1:1 por monto y fecha con tolerancia.
- Deben aplicarse reglas por cuenta, tienda y tipo.
- No debe permitirse reutilizacion de movimientos conciliados.

### RF-06 Matching agrupado
- Deben proponerse grupos 1 banco a N JDE dentro de tolerancia.
- Debe respetarse limite de tamano de grupo configurable.
- Debe requerirse aprobacion del usuario para su aplicacion.

### RF-07 Matching agrupado inverso
- Deben proponerse grupos N banco a 1 JDE dentro de tolerancia.
- Deben aplicarse reglas de consistencia para evitar falsos positivos.
- Debe requerirse aprobacion del usuario para su aplicacion.

### RF-08 Validacion interactiva
- Debe mostrarse detalle por agrupacion propuesta.
- Debe permitirse aceptar o rechazar por grupo y en bloque.

### RF-09 Reporte final
- Debe generarse Excel con resumen, conciliados y pendientes.
- Deben incluirse conteos por tipo de conciliacion.

### RF-10 Write-back
- Debe marcarse CONCILIADO y FECHA CONCILIACION por Aux_Fact.
- Debe aplicarse unicamente en cuentas habilitadas.
- Debe preservarse archivo fuente mediante salida descargable.

### RF-11 Modulo batch
- Debe operar de forma independiente al flujo principal.
- Debe permitir confirmacion de varios grupos y generacion final unica.

### RF-12 Analisis historico
- Debe cruzarse conciliacion anterior contra periodo actual.
- Debe clasificarse estatus sin alterar resultados vigentes.

## 5. Requisitos no funcionales

- Usabilidad: flujo entendible para usuario operativo.
- Precision: control de falsos positivos por reglas de negocio.
- Mantenibilidad: separacion modular por responsabilidad.
- Portabilidad: compatibilidad con Python 3.10+.
- Trazabilidad: registro de eventos relevantes.

## 6. Restricciones

- Procesamiento en memoria (sin base de datos).
- Sin autenticacion integrada en esta version.
- Dependencia de calidad de archivos de entrada.

## 7. Criterio de aceptacion operativa

La ejecucion se considera valida cuando:
- No se presentan errores de parseo o validacion.
- Solo se aplican agrupaciones aprobadas.
- Se obtiene reporte final y write-back cuando corresponda.
