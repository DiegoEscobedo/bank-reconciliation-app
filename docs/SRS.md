# Especificación de Requisitos de Software (SRS)
## Sistema de Conciliación Bancaria

| Campo | Valor |
|---|---|
| Versión | 1.4 |
| Fecha | 08/04/2026 |
| Autor | Diego Escobedo |
| Estado | Vigente |
| Cambios | Prioridad de exactos por unicidad, CONCILIADO=0 como pendiente, normalización de cuenta `.0`, regla CARGO POR DISPERSION↔NOMINA, normalización conservadora de signo, guías de deploy |

---

## 1. Introducción

### 1.1 Propósito

Este documento define los requisitos funcionales y no funcionales del **Sistema de Conciliación Bancaria**, una aplicación que automatiza la comparación entre movimientos del estado de cuenta bancario y los registros del sistema contable JD Edwards (JDE), generando reportes de conciliación y marcando el papel de trabajo.

### 1.2 Alcance

El sistema permite:
- Cargar archivos de movimientos bancarios (BBVA, Banorte, Scotiabank, Mercado Pago, NetPay) y del sistema JDE.
- Ejecutar un motor de conciliación automática con matching exacto, agrupado e inverso.
- Revisar y aprobar agrupaciones propuestas de manera interactiva.
- Generar un reporte Excel con los resultados clasificados.
- Marcar como conciliadas las filas correspondientes en el Papel de Trabajo original (cuentas 6614 y 7133).
- Aplicar filtro previo para Mercado Pago por grupos de color cuyo total exista en Scotiabank.
- Ejecutar análisis histórico de pendientes en modo solo lectura.

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
- Formatos bancarios soportados:
  - BBVA: Estado de cuenta CSV/Excel
  - Banorte: Estado de cuenta CSV/Excel
  - Scotiabank: Estado de cuenta Excel (14 columnas)
  - Mercado Pago: Estado de cuenta Excel con filas de color
  - NetPay: Reporte de nómina Excel
- Papel de Trabajo: Excel R550911A1 con Aux_Fact (Cuentas 6614, 7133)

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

**Descripción:** El sistema debe aceptar archivos de estado de cuenta de múltiples bancos (BBVA, Banorte, Scotiabank, Mercado Pago, NetPay) y archivos de tipo REPORTE CAJA.

**Criterios de aceptación:**
- Acepta `.csv` y `.xlsx` / `.xls`.
- Detecta automáticamente el banco por la estructura del archivo (análisis de encabezados y estructura).
- **Robustez de parseo**: Los parsers normalizan nombres de columnas para manejar variaciones en:
  - Acentos (e.g., "DEPÓSITOS" vs "DEPOSITOS")
  - Espacios extra
  - Variaciones en capitalización
- **Casos especiales:**
  - **Scotiabank**: Valida que tenga al menos 14 columnas; si faltan columnas, usa Series vacíos sin crashear.
  - **Mercado Pago**: Conserva filas con estado `Aprobado`/`Aprovado`; usa `COBRO` para match contra JDE y `TOTAL A RECIBIR` para agrupación por color contra Scotiabank.
  - **NetPay**: Detecta por presencia de columnas específicas (Sucursal, Empleado, etc).
- Si se carga un REPORTE CAJA junto con el estado de cuenta, lo usa para enriquecer los movimientos bancarios con los campos `tienda` y `tipo_pago`.
- Si solo se carga un REPORTE CAJA (sin estado de cuenta), lo usa como fuente bancaria.
- Si los nombres de columnas requeridas no se encuentran (incluso después de normalización), el parser lanza un error descriptivo indicando las columnas disponibles.

---

### RF-02 — Carga de archivos JDE

**Descripción:** El sistema debe aceptar archivos del sistema JDE en dos formatos:
1. CSV R550911A1 (Auxiliar de Contabilidad).
2. Excel "Papel de Trabajo" (para cuentas 6614 y 7133).

**Criterios de aceptación:**
- Para CSV: lee el encabezado a partir de la fila 3, extrae fecha, cuenta, monto, tipo de documento y descripción.
- Para Papel de Trabajo Excel:
  - Detecta automáticamente si es Excel con estructura Papel de Trabajo (presencia de columna `Aux_Fact`).
  - Omite filas ya conciliadas y conserva como pendientes filas con `CONCILIADO` vacío o en `0`/`0.0`.
  - Extrae el identificador `Aux_Fact` para poder marcar archivos durante el write-back.
  - Valida que tenga las columnas requeridas (`Aux_Fact`, `Importe`, `CONCILIADO`, `FECHA CONCILIACION`).
- Ambos formatos producen el mismo esquema de columnas normalizado.
- Detecta automáticamente la cuenta (6614 o 7133) para determinar si es elegible para write-back.

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

**Reglas adicionales implementadas de normalización bancaria:**
- Si un monto aparece en columna de retiro, se normaliza con signo negativo.
- Si un monto aparece en columna de depósito con signo negativo y no existe retiro, se conserva el signo negativo.
- Se previenen inconsistencias por signos contradictorios entre columna y valor.

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
- Dos movimientos coinciden si la diferencia de montos absolutos es ≤ `AMOUNT_TOLERANCE` (0.50 por defecto).
- La diferencia de fechas debe ser ≤ `DATE_TOLERANCE_DAYS` (2 días por defecto).
- **Validación OBLIGATORIA de tienda:** 
  - Si el banco tiene tienda definida, el JDE DEBE coincidir en tienda exactamente.
  - Si el banco NO tiene tienda, NO acepta JDE con tienda definida (previene matches ambiguos).
  - Solo se aceptan matches exactos cuando ambos carecen de tienda O ambos tienen la misma tienda.
- Filtrado por tipo: Si el movimiento bancario es de comisión, solo se emparejan con movimientos JDE que también sean comisión.
- Compatibilidad de cuenta por equivalencia de sufijo y normalización robusta de tokens numéricos (incluye cuentas con formato texto-float, por ejemplo `20305077133.0`).
- Resolución de conflictos de unicidad: cuando hay múltiples candidatos exactos, el sistema prioriza emparejar primero los movimientos de banco con menor número de candidatos válidos.
- Cada movimiento solo puede participar en un match (no se reutilizan).
- Los movimientos matcheados se marcan como `is_matched = True`.

---

### RF-06 — Matching inverso

**Descripción:** El motor debe proponer agrupaciones donde N movimientos bancarios (N ≤ `MAX_GROUP_SIZE`) suman el monto de un único movimiento JDE pendiente.

**Criterios de aceptación:**
- Solo se consideran movimientos sin match exacto.
- La diferencia entre la suma de movimientos bancarios y el monto JDE debe ser ≤ `AMOUNT_TOLERANCE`.
- **Validación de tienda al confirmar:**
  - Si TODOS los movimientos bancarios provienen de la MISMA tienda → deben coincidir con tienda del JDE (o JDE sin tienda).
  - Si movimientos bancarios provienen de múltiples tiendas → RECHAZA automáticamente (falso positivo).
  - Sin tienda en JDE o bancos → se aceptan sin restricción.
- Las agrupaciones inversas se presentan como propuestas al usuario.

---

### RF-07 — Matching agrupado

**Descripción:** El motor debe proponer agrupaciones donde la suma de N movimientos JDE (N ≤ `MAX_GROUP_SIZE`) se aproxima al monto de un movimiento bancario pendiente.

**Criterios de aceptación:**
- Solo se consideran movimientos no matcheados en la fase exacta.
- El tamaño máximo del grupo es `MAX_GROUP_SIZE` (10 por defecto).
- La diferencia entre el monto bancario y la suma del grupo debe ser ≤ `AMOUNT_TOLERANCE`.
- **Durante la búsqueda de agrupaciones:** Mayor flexibilidad para explorar posibilidades.
- **Al confirmar:**
  - Validación de tienda: Si TODOS los JDE de la agrupación son de UNA tienda diferente a la tienda del banco → RECHAZA automáticamente (previene falsos positivos).
  - Si bancos o JDE carecen de tienda, se aceptan sin restricción.
- Las agrupaciones se presentan como **propuestas**; el usuario las aprueba o rechaza antes de confirmar.
- Regla de negocio específica implementada:
  - Banco CARGO POR DISPERSION solo puede agrupar con JDE NOMINA.
  - En agrupación inversa, JDE NOMINA solo puede usar bancos CARGO POR DISPERSION.

---

### RF-08 — Revisión interactiva de agrupaciones (modo Streamlit)

**Descripción:** El usuario debe poder revisar cada agrupación propuesta (tanto agrupadas como inversas) y aprobarla o rechazarla individualmente.

**Criterios de aceptación:**
- La UI muestra cada grupo con: monto bancario, movimientos JDE del grupo, diferencia y tienda (si aplica).
- El usuario puede seleccionar / deseleccionar grupos con un checkbox.
- Solo los grupos aprobados se incluyen en el resultado final.
- Se muestran tanto agrupaciones forward (1 banco ← N JDE) como inversas (N banco → 1 JDE) de forma clara.

---

### RF-09 — Generación de reporte Excel

**Descripción:** El sistema debe generar un archivo Excel con los resultados de la conciliación.

**Criterios de aceptación:**
- El archivo contiene 4 hojas: **Resumen**, **Conciliados**, **Pendientes Banco**, **Pendientes JDE**.
- **Resumen** incluye: total de movimientos banco y JDE, conteo de matches exactos y agrupados (incluyendo inversos), conteo de pendientes.
- **Conciliados** incluye por cada match: tipo (Exacto/Agrupado), datos banco, datos JDE, diferencia.
- **Pendientes** muestran los movimientos sin match con todos sus campos.
- El archivo tiene formato visual: encabezados con color, filas alternas, formatos de fecha y moneda.
- El nombre del archivo incluye timestamp: `conciliacion_YYYYMMDD_HHMMSS.xlsx`.

---

### RF-10 — Write-back al Papel de Trabajo

**Descripción:** El sistema debe poder marcar como conciliadas las filas correspondientes en el Papel de Trabajo original del usuario (solo para cuentas 6614 y 7133).

**Criterios de aceptación:**
- Aplica solo si: archivo JDE es Excel Y cuenta está en `PAPEL_TRABAJO_ACCOUNTS` (6614, 7133).
- Localiza automáticamente la hoja `AUX CONTABLE` en el archivo original.
- Identifica las columnas `CONCILIADO` y `FECHA CONCILIACION` por nombre (no por posición).
- Escribe `"Sí"` en `CONCILIADO` y la fecha más reciente de los movimientos bancarios conciliados en `FECHA CONCILIACION` para cada `Aux_Fact` conciliado.
- La fecha de conciliación es automáticamente la más reciente del banco (no la fecha de ejecución).
- Aplica aislamiento por cuenta: solo marca filas del Papel cuya cuenta (`CUENTA XXXX`) coincide con las cuentas del banco en conciliación.
- Para cuentas bancarias largas, compara por sufijo (últimos 4 dígitos) contra cuenta corta del Papel.
- El resto del archivo (fórmulas, formatos, otras hojas) permanece intacto.
- El archivo modificado se entrega como descarga en bytes (sin sobreescribir el original directamente).

---

### RF-11 — Uso por línea de comandos (CLI)

**Descripción:** El sistema debe ser operable sin interfaz gráfica.

**Criterios de aceptación:**
- Acepta argumentos `--bank`, `--jde` y `--output`.
- `--bank` acepta una o varias rutas de archivo.
- Imprime un resumen en consola al finalizar.
- Termina con código de salida `1` ante errores de validación o archivo no encontrado.

---

### RF-12 — Análisis histórico de pendientes (solo lectura)

**Descripción:** El sistema debe permitir cargar una conciliación anterior y cruzar sus pendientes contra el período actual para clasificar su estatus.

**Criterios de aceptación:**
- Parsea pendientes históricos por sección (`mas`, `menos`) desde el archivo de conciliación anterior.
- Cruza cada pendiente por monto y fecha contra: conciliados banco/JDE y pendientes banco/JDE del período actual.
- Exige misma cuenta en el cruce histórico (modo estricto fijo), aceptando equivalencia por sufijo para cuenta larga/corta.
- Clasifica en `CONCILIADO`, `PENDIENTE_BANCO`, `PENDIENTE_JDE`, `AUN_PENDIENTE`.
- No modifica la conciliación del período actual ni ejecuta write-back; solo muestra métricas/tablas y permite descarga del análisis.

---

### RF-13 — Soporte de despliegue en servidor propio

**Descripción:** El proyecto debe incluir artefactos de referencia para despliegue en servidor Linux sin afectar operación local.

**Criterios de aceptación:**
- Existe una guía de despliegue en `deploy/README_SERVER.md`.
- Existe unidad systemd de referencia en `deploy/systemd/bank-reconciliation.service`.
- Existe configuración Nginx de referencia en `deploy/nginx/bank-reconciliation.conf`.
- Existe script de actualización operativa en `deploy/scripts/deploy.sh`.
- La ejecución local se mantiene con `streamlit run app.py` sin dependencias del despliegue.

---

## 4. Requisitos No Funcionales

### RNF-01 — Rendimiento
El procesamiento de archivos de hasta 10,000 movimientos combinados (banco + JDE) debe completarse en menos de 60 segundos en hardware estándar de oficina.

### RNF-02 — Usabilidad
La interfaz Streamlit debe ser operable sin conocimientos técnicos: carga de archivos por arrastrar, visualización de resultados en tabla y descarga de reportes en un clic. Incluye selector de fecha para el nombre del archivo descargado.

### RNF-03 — Mantenibilidad
Cada capa (parsers, normalizers, engine, reporting) debe estar aislada en su propio módulo, permitiendo añadir soporte para nuevos bancos o formatos sin modificar el motor de conciliación.

### RNF-04 — Portabilidad
El sistema debe ejecutarse en Windows, macOS y Linux con Python 3.10+.

### RNF-05 — Trazabilidad
Todas las operaciones relevantes deben quedar registradas en el sistema de logs (`logs/`), incluyendo conteos de movimientos, tiempos, bancos detectados y errores de parseo.

### RNF-06 — Tolerancia a variaciones de datos
El sistema debe manejar diferencias de ±0.50 en montos y ±2 días en fechas entre banco y JDE, configurables en `config/settings.py`.

### RNF-07 — Robustez frente a variaciones de formato
Los parsers y motor de matching deben tolerar:
- **Parseo:** Nombres de columnas con acentos, espacios extra, capitalización variable
- **Parseo:** Diferentes ordenamientos de columnas, columnas faltantes (ej: Scotiabank con <14 columnas)
- **Parseo:** Filas con color (Mercado Pago)
- **Matching:** Prevención de falsos positivos - rechaza agrupaciones donde tiendas no coinciden
  - Exacto: Obligatorio match de tienda si existe en alguno de los movimientos
  - Agrupado: Rechaza si todos los JDE son de una tienda diferente al banco
  - Inverso: Rechaza si bancos provienen de múltiples tiendas

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

### 6.3 Estado de cuenta bancario (Scotiabank)
- Formato Excel
- Estructur esperada: 14 columnas
- Validación: Si tiene <14 columnas, usa Series vacíos sin fallar

### 6.4 Estado de cuenta bancario (Mercado Pago)
- Formato Excel
- Filas válidas: estado `Aprobado` o `Aprovado`
- Monto para conciliación con JDE: columna `COBRO`
- Monto para agrupación por color vs Scotiabank: columna `TOTAL A RECIBIR`

### 6.5 Nómina (NetPay)
- Formato Excel
- Columnas esperadas: Sucursal, Empleado, Concepto, Cantidad

### 6.6 JDE — CSV R550911A1
- Encabezado en fila 3 (índice 2)
- Mínimo 23 columnas
- Columnas relevantes: cuenta (col 9), tipo doc (12), documento (13), fecha (14), importe (16), descripción (21, 22)

### 6.7 JDE — Papel de Trabajo Excel
- Hoja `AUX CONTABLE` 
- Columnas requeridas: `Aux_Fact`, `Importe`, `CONCILIADO`, `FECHA CONCILIACION`
- Filas con `CONCILIADO` no vacío son ignoradas (ya conciliadas)
- Solo para cuentas 6614 (BBVA) y 7133 (Scotiabank)
