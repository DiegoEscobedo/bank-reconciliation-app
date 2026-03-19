# Especificación de Requisitos de Software (SRS)
## Sistema de Conciliación Bancaria

| Campo | Valor |
|---|---|
| Versión | 1.1 |
| Fecha | 19/03/2026 |
| Autor | Diego Escobedo |
| Estado | Vigente |

---

## 1. Introducción

### 1.1 Propósito

Este documento define los requisitos funcionales y no funcionales del **Sistema de Conciliación Bancaria**, una aplicación que automatiza la comparación entre movimientos del estado de cuenta bancario y los registros del sistema contable JD Edwards (JDE), generando reportes de conciliación y marcando el papel de trabajo.

### 1.2 Alcance

El sistema permite:
- Cargar archivos de movimientos bancarios (BBVA, Banorte) y del sistema JDE.
- Ejecutar un motor de conciliación automática con matching exacto y agrupado.
- Revisar y aprobar agrupaciones propuestas de manera interactiva.
- Generar un reporte Excel con los resultados clasificados.
- Marcar como conciliadas las filas correspondientes en el Papel de Trabajo original.

### 1.3 Definiciones y acrónimos

| Término | Definición |
|---|---|
| JDE | JD Edwards — sistema contable ERP utilizado por la empresa |
| Papel de Trabajo | Archivo Excel de control continuo con movimientos JDE y columnas CONCILIADO / FECHA CONCILIACION |
| REPORTE CAJA | Archivo auxiliar Excel con movimientos de punto de venta por tienda |
| Match exacto | Correspondencia 1:1 entre un movimiento bancario y uno JDE por monto y fecha |
| Match agrupado | Correspondencia 1:N donde varios movimientos JDE suman el monto de un movimiento bancario |
| Aux_Fact | Identificador único de cada movimiento en el Papel de Trabajo |
| Pendiente | Movimiento sin correspondencia tras el proceso de conciliación |

### 1.4 Referencias

- Reporte JDE: R550911A1 (Auxiliar de Contabilidad)
- Formatos bancarios: Estado de cuenta BBVA CSV, Banorte CSV/Excel

---

## 2. Descripción General del Sistema

### 2.1 Perspectiva del producto

El sistema es una aplicación standalone Python que opera en dos modos:
- **Interfaz web** (Streamlit): uso interactivo con carga de archivos vía navegador.
- **CLI** (línea de comandos): uso automatizable por scripts.

### 2.2 Funciones principales

1. Parseo y normalización de archivos bancarios y JDE.
2. Validación del esquema de datos antes de procesar.
3. Matching automático de movimientos (exacto y agrupado).
4. Revisión interactiva de agrupaciones propuestas.
5. Generación de reporte Excel de conciliación.
6. Escritura de resultados en el Papel de Trabajo original.

### 2.3 Usuarios

| Tipo de usuario | Descripción |
|---|---|
| Analista contable | Usuario principal; carga archivos, revisa agrupaciones y descarga reportes |
| Administrador | Desarrollador que configura parámetros y da mantenimiento al sistema |

### 2.4 Restricciones

- El sistema opera exclusivamente con archivos `.xlsx`, `.xls` y `.csv`.
- Requiere Python 3.10 o superior.
- No tiene base de datos; todos los datos son procesados en memoria.
- No gestiona autenticación ni control de acceso.

---

## 3. Requisitos Funcionales

### RF-01 — Carga de archivos bancarios

**Descripción:** El sistema debe aceptar uno o más archivos de estado de cuenta de bancos soportados (BBVA, Banorte) y archivos de tipo REPORTE CAJA.

**Criterios de aceptación:**
- Acepta `.csv` y `.xlsx` / `.xls`.
- Detecta automáticamente el banco por la estructura del archivo.
- **Robustez de parseo**: El parser BBVA y Banorte normalizan nombres de columnas para manejar variaciones en:
  - Acentos (e.g., "DEPÓSITOS" vs "DEPOSITOS")
  - Espacios extra
  - Variaciones en capitalización
  - Esta flexibilidad previene errores por diferencias de formato en archivos exportados desde distintos sistemas
- Si se carga un REPORTE CAJA junto con el estado de cuenta, lo usa para enriquecer los movimientos bancarios con los campos `tienda` y `tipo_banco`.
- Si solo se carga un REPORTE CAJA (sin estado de cuenta), lo usa como fuente bancaria.
- Si los nombres de columnas requeridas no se encuentran (incluso después de normalización), el parser lanza un error descriptivo indicando las columnas disponibles.

---

### RF-02 — Carga de archivos JDE

**Descripción:** El sistema debe aceptar archivos del sistema JDE en dos formatos:
1. CSV R550911A1 (Auxiliar de Contabilidad).
2. Excel "Papel de Trabajo".

**Criterios de aceptación:**
- Para CSV: lee el encabezado a partir de la fila 3, extrae fecha, cuenta, monto, tipo de documento y descripción.
- Para Papel de Trabajo Excel: omite filas donde la columna `CONCILIADO` ya tenga valor (filas ya conciliadas en el pasado).
- Ambos formatos producen el mismo esquema de columnas normalizado.

---

### RF-03 — Normalización de datos

**Descripción:** Los datos crudos de banco y JDE deben ser transformados a un esquema estándar antes de ser procesados.

**Esquema estándar requerido:**

| Columna | Tipo | Descripción |
|---|---|---|
| `account_id` | string | Número de cuenta (últimos dígitos) |
| `movement_date` | datetime | Fecha del movimiento |
| `description` | string | Concepto o descripción |
| `amount_signed` | float | Monto con signo (+ crédito, - débito) |
| `abs_amount` | float | Valor absoluto del monto |
| `movement_type` | string | Tipo de movimiento |
| `source` | string | `BANK` o `JDE` |

---

### RF-04 — Validación de schema

**Descripción:** Antes de ejecutar el motor de conciliación, el sistema debe validar que los DataFrames cumplan el esquema estándar.

**Criterios de aceptación:**
- Verifica que existan todas las columnas requeridas; lanza error si falta alguna.
- Verifica tipos de dato: `movement_date` debe ser `datetime64`, `amount_signed` y `abs_amount` deben ser numéricos, `account_id` debe ser string.
- Verifica que `account_id`, `movement_date` y `abs_amount` no tengan valores nulos.
- Los errores se comunican con mensajes específicos indicando la fuente (`BANK` / `JDE`) y la columna afectada.

---

### RF-05 — Matching exacto

**Descripción:** El motor debe encontrar correspondencias 1:1 entre movimientos bancarios y JDE basándose en monto y fecha.

**Criterios de aceptación:**
- Dos movimientos coinciden si la diferencia de montos absolutos es ≤ `AMOUNT_TOLERANCE` (0.10 por defecto).
- La diferencia de fechas debe ser ≤ `DATE_TOLERANCE_DAYS` (1 día por defecto).
- Si ambos DataFrames contienen columnas de tienda (`tienda`, `tipo_banco`, `tipo_jde`), se usa ese dato como discriminador adicional antes del monto.
- Cada movimiento solo puede participar en un match (no se reutilizan).
- Los movimientos matcheados se marcan como `is_matched = True`.

---

### RF-06 — Matching agrupado

**Descripción:** El motor debe proponer agrupaciones donde la suma de N movimientos JDE (N ≤ `MAX_GROUP_SIZE`) se aproxima al monto de un movimiento bancario pendiente.

**Criterios de aceptación:**
- Solo se consideran movimientos no matcheados en la fase exacta.
- El tamaño máximo del grupo es `MAX_GROUP_SIZE` (10 por defecto).
- La diferencia entre el monto bancario y la suma del grupo debe ser ≤ `AMOUNT_TOLERANCE`.
- Las agrupaciones se presentan como **propuestas**; el usuario las aprueba o rechaza antes de confirmar.

---

### RF-07 — Revisión interactiva de agrupaciones (modo Streamlit)

**Descripción:** El usuario debe poder revisar cada agrupación propuesta y aprobarla o rechazarla individualmente.

**Criterios de aceptación:**
- La UI muestra cada grupo con: monto bancario, movimientos JDE del grupo, diferencia y tienda (si aplica).
- El usuario puede seleccionar / deseleccionar grupos con un checkbox.
- Solo los grupos aprobados se incluyen en el resultado final.

---

### RF-08 — Generación de reporte Excel

**Descripción:** El sistema debe generar un archivo Excel con los resultados de la conciliación.

**Criterios de aceptación:**
- El archivo contiene 4 hojas: **Resumen**, **Conciliados**, **Pendientes Banco**, **Pendientes JDE**.
- **Resumen** incluye: total de movimientos banco y JDE, conteo de matches exactos y agrupados, conteo de pendientes.
- **Conciliados** incluye por cada match: tipo (Exacto/Agrupado), datos banco, datos JDE, diferencia.
- **Pendientes** muestran los movimientos sin match con todos sus campos.
- El archivo tiene formato visual: encabezados con color, filas alternas, formatos de fecha y moneda.
- El nombre del archivo incluye timestamp: `conciliacion_YYYYMMDD_HHMMSS.xlsx`.

---

### RF-09 — Write-back al Papel de Trabajo

**Descripción:** El sistema debe poder marcar como conciliadas las filas correspondientes en el Papel de Trabajo original del usuario.

**Criterios de aceptación:**
- Localiza automáticamente la hoja `AUX CONTABLE` en el archivo original.
- Identifica las columnas `CONCILIADO` y `FECHA CONCILIACION` por nombre (no por posición).
- Escribe `"Sí"` en `CONCILIADO` y la fecha del proceso en `FECHA CONCILIACION` para cada `Aux_Fact` conciliado.
- El resto del archivo (fórmulas, formatos, otras hojas) permanece intacto.
- El archivo modificado se entrega como descarga en bytes (sin sobreescribir el original directamente).

---

### RF-10 — Uso por línea de comandos (CLI)

**Descripción:** El sistema debe ser operable sin interfaz gráfica.

**Criterios de aceptación:**
- Acepta argumentos `--bank`, `--jde` y `--output`.
- `--bank` acepta una o varias rutas de archivo.
- Imprime un resumen en consola al finalizar.
- Termina con código de salida `1` ante errores de validación o archivo no encontrado.

---

## 4. Requisitos No Funcionales

### RNF-01 — Rendimiento
El procesamiento de archivos de hasta 5,000 movimientos combinados (banco + JDE) debe completarse en menos de 30 segundos en hardware estándar de oficina.

### RNF-02 — Usabilidad
La interfaz Streamlit debe ser operable sin conocimientos técnicos: carga de archivos por arrastrar, visualización de resultados en tabla y descarga de reportes en un clic.

### RNF-03 — Mantenibilidad
Cada capa (parsers, normalizers, matching, reporting) debe estar aislada en su propio módulo, permitiendo añadir soporte para nuevos bancos o formatos sin modificar el motor.

### RNF-04 — Portabilidad
El sistema debe ejecutarse en Windows, macOS y Linux con Python 3.10+.

### RNF-05 — Trazabilidad
Todas las operaciones relevantes deben quedar registradas en el sistema de logs (`logs/`), incluyendo conteos de movimientos, tiempos y errores.

### RNF-06 — Tolerancia a variaciones de datos
El sistema debe manejar diferencias de ±0.10 en montos y ±1 día en fechas entre banco y JDE, configurables en `config/settings.py`.

---

## 5. Restricciones del sistema

| Restricción | Detalle |
|---|---|
| Lenguaje | Python 3.10+ |
| Interfaz web | Streamlit (no soporta otros frameworks) |
| Archivos de entrada | `.xlsx`, `.xls`, `.csv` únicamente |
| Persistencia | Sin base de datos; procesamiento en memoria |
| Seguridad | Sin autenticación; uso en red local o máquina personal |

---

## 6. Requisitos de datos de entrada

### 6.1 Estado de cuenta bancario (BBVA)
- Formato CSV o Excel
- Columnas esperadas: Fecha, Descripción, DEPÓSITOS, RETIROS, SALDO

### 6.2 Estado de cuenta bancario (Banorte)
- Formato CSV o Excel
- Fila 0: número de cuenta; fila 1: encabezados
- Columnas esperadas: Fecha, Descripción, Cargo, Abono

### 6.3 JDE — CSV R550911A1
- Encabezado en fila 3 (índice 2)
- Mínimo 23 columnas
- Columnas relevantes: cuenta (col 9), tipo doc (12), documento (13), fecha (14), importe (16), descripción (21, 22)

### 6.4 JDE — Papel de Trabajo Excel
- Hoja `AUX CONTABLE`
- Columnas requeridas: `Aux_Fact`, `Importe`, `CONCILIADO`, `FECHA CONCILIACION`
- Filas con `CONCILIADO` no vacío son ignoradas (ya conciliadas)
