# Especificación de Diseño de Software (SDS)
## Sistema de Conciliación Bancaria

| Campo | Valor |
|---|---|
| Versión | 1.0 |
| Fecha | 03/03/2026 |
| Autor | Diego Escobedo |
| Estado | Borrador |

---

## 1. Introducción

Este documento describe la arquitectura, los módulos, el flujo de datos y las decisiones de diseño del Sistema de Conciliación Bancaria. Está dirigido a desarrolladores que necesiten mantener, extender o comprender el sistema a nivel técnico.

---

## 2. Arquitectura General

El sistema sigue una **arquitectura por capas** donde cada capa tiene una única responsabilidad y se comunica solo con la capa adyacente. No existe base de datos; todos los datos fluyen como `pandas.DataFrame` entre módulos.

```
┌─────────────────────────────────────────────────────────────┐
│                  Capa de Presentación                       │
│           app.py (Streamlit)  │  main.py (CLI)              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  Orquestador (main.py)                      │
│   run_pipeline / run_pipeline_stage1 / run_pipeline_stage2  │
└──┬──────────┬───────────────────┬──────────────┬────────────┘
   │          │                   │              │
   ▼          ▼                   ▼              ▼
Parsers  Normalizers          Validator      Engine
   │          │                   │              │
   └──────────┴───────────────────┘              │
                      │                          │
                      ▼                          ▼
                 DataFrames              ReconciliationEngine
                 (bank_df,              (exact + grouped matching)
                  jde_df)                        │
                                                 ▼
                                          ExcelReporter
                                   (reporte + write-back)
```

---

## 3. Estructura de Módulos

```
bank-reconciliation-app/
├── app.py                          # Interfaz Streamlit
├── main.py                         # Orquestador y CLI
├── config/
│   ├── settings.py                 # Parámetros globales configurables
│   └── __init__.py
├── src/
│   ├── parsers/
│   │   ├── bank_parser.py          # Parser bancario (BBVA, Banorte, Reporte Caja)
│   │   └── jde_parser.py           # Parser JDE (CSV R550911A1 y Papel de Trabajo)
│   ├── normalizers/
│   │   ├── bank_normalizer.py      # Normalización a esquema estándar (banco)
│   │   └── jde_normalizer.py       # Normalización a esquema estándar (JDE)
│   ├── validacion/
│   │   └── schema_validator.py     # Validación del esquema estándar
│   ├── matching/
│   │   ├── reconciliation_engine.py # Motor principal
│   │   ├── exact_matcher.py        # Lógica de matching exacto
│   │   └── grouped_matcher.py      # Lógica de matching agrupado (subset sum)
│   ├── reporting/
│   │   └── excel_reporter.py       # Generación de reporte + write-back
│   └── utils/
│       ├── amount_utils.py         # Utilidades de comparación de montos
│       ├── date_utils.py           # Utilidades de parseo y comparación de fechas
│       └── logger.py               # Configuración del logger
└── data/
    ├── raw/bank/                   # Archivos de entrada bancarios
    ├── raw/jde/                    # Archivos de entrada JDE
    └── output/reconciliations/     # Reportes generados
```

---

## 4. Descripción de Componentes

### 4.1 `config/settings.py`

Centraliza todos los parámetros configurables del sistema. No contiene lógica.

| Parámetro | Valor por defecto | Descripción |
|---|---|---|
| `AMOUNT_TOLERANCE` | 0.10 | Diferencia máxima de monto permitida para un match |
| `DATE_TOLERANCE_DAYS` | 1 | Diferencia máxima de días permitida |
| `MAX_GROUP_SIZE` | 10 | Máximo de movimientos JDE por agrupación |
| `ROUND_DECIMALS` | 2 | Decimales para redondeo de montos |
| `TIENDA_ABBREV` | dict | Mapeo nombre completo de tienda → abreviatura JDE |

---

### 4.2 `src/parsers/bank_parser.py`

**Responsabilidad:** Leer archivos de estado de cuenta bancario y retornar un DataFrame crudo.

**Diseño:** Patrón de estrategia mediante herencia.

```
BankParser
    └── detecta el banco y delega a sub-parser
_BaseBankParser
    ├── _BBVAParser     → detecta columnas DEPÓSITOS / RETIROS
    ├── _BanorteParser  → detecta encabezado en fila 1 con número de cuenta en fila 0
    └── _ReporteCajaParser → detecta hoja/formato de reporte de punto de venta
```

**Flujo de detección:**
1. Lee el archivo completo sin header.
2. Itera sobre `_PARSERS` probando si cada sub-parser reconoce el formato.
3. Delega el parseo al primero que coincida.
4. Añade columna `bank` con el nombre del banco para identificar REPORTE CAJA.

---

### 4.3 `src/parsers/jde_parser.py`

**Responsabilidad:** Leer archivos JDE en dos formatos distintos.

**Clases:**

| Clase | Formato | Detección |
|---|---|---|
| `JDEParser` | CSV R550911A1 | Extensión `.csv` o Excel con encabezado en fila 2 |
| `PapelTrabajoParser` | Excel Papel de Trabajo | Extensión `.xlsx`/`.xls` con hoja `AUX CONTABLE` |

**Comportamiento especial de `PapelTrabajoParser`:**
- Solo carga filas donde `CONCILIADO` está vacío.
- Extrae `Aux_Fact` para el proceso de write-back posterior.
- Mapea nombres de tienda usando `TIENDA_ABBREV`.

---

### 4.4 `src/normalizers/`

**Responsabilidad:** Transformar DataFrames crudos al esquema estándar definido en el SRS (RF-03).

**`BankNormalizer.normalize(df)`:**
- Renombra columnas al esquema estándar.
- Convierte `movement_date` a `datetime64`.
- Calcula `abs_amount = abs(amount_signed)`.
- Asigna `source = "BANK"`.

**`JDENormalizer.normalize(df)`:**
- Misma lógica adaptada a la estructura JDE.
- Asigna `source = "JDE"`.
- Preserva columnas extra: `doc_type`, `document`, `tienda`, `tipo_jde`.

---

### 4.5 `src/validacion/schema_validator.py`

**Responsabilidad:** Garantizar que los DataFrames cumplan el esquema antes de procesarlos.

**Clase:** `DataFrameSchemaValidator`

**Métodos públicos:**
- `validate_bank_dataframe(df)` → llama las 3 validaciones internas con `source_name="BANK"`
- `validate_jde_dataframe(df)` → ídem con `source_name="JDE"`

**Validaciones internas:**

| Método | Qué verifica |
|---|---|
| `_validate_required_columns` | Presencia de las 7 columnas obligatorias |
| `_validate_data_types` | Tipos de `movement_date`, `amount_signed`, `abs_amount`, `account_id` |
| `_validate_null_values` | Nulos en `account_id`, `movement_date`, `abs_amount` |

**Errores:** Lanza `SchemaValidationError` (hereda de `Exception`) con mensaje descriptivo.

---

### 4.6 `src/matching/reconciliation_engine.py`

**Responsabilidad:** Orquestar el proceso de conciliación en sus dos fases.

**Clase:** `ReconciliationEngine`

#### Modo directo (`reconcile`)
```
reconcile(bank_df, jde_df)
    └── reconcile_interactive(bank_df, jde_df)
        └── confirm_grouped_matches(result, all_group_ids)
```
Aprueba todas las agrupaciones automáticamente. Usado en CLI.

#### Modo interactivo (`reconcile_interactive` + `confirm_grouped_matches`)
```
Fase 1: reconcile_interactive(bank_df, jde_df)
    1. Copia los DataFrames y añade columna is_matched=False
    2. _perform_exact_matching → marca is_matched en los matcheados
    3. _propose_grouped_matches → genera propuestas sin aplicarlas
    Retorna: dict con exact_matches + proposed_grouped_matches

Fase 2: confirm_grouped_matches(interactive_result, approved_group_ids)
    1. Aplica solo los grupos cuyo group_id está en approved_group_ids
    2. Construye listas de pendientes (no matcheados)
    3. Construye el dict de resultados final
    4. Calcula el summary
```

#### Discriminación por tienda
Cuando los DataFrames tienen columnas `tienda` y `tipo_banco`/`tipo_jde`, el motor aplica el mapa `_TIPO_MAP` para verificar compatibilidad de tipo de pago antes de comparar montos. Esto reduce falsos positivos sin romper la lógica para archivos sin esas columnas.

#### Estructura del dict de resultados

```python
{
    "exact_matches":              list[dict],   # Matches 1:1
    "grouped_matches":            list[dict],   # Matches 1:N confirmados
    "conciliated_bank_movements": pd.DataFrame, # Movimientos banco matcheados
    "pending_bank_movements":     pd.DataFrame, # Movimientos banco sin match
    "pending_jde_movements":      pd.DataFrame, # Movimientos JDE sin match
    "_bank_df_full":              pd.DataFrame, # DataFrame banco completo
    "_jde_df_full":               pd.DataFrame, # DataFrame JDE completo
    "summary": {
        "total_bank_movements":   int,
        "total_jde_movements":    int,
        "exact_matches_count":    int,
        "grouped_matches_count":  int,
        "pending_bank_count":     int,
        "pending_jde_count":      int,
    }
}
```

#### Estructura de un match exacto

```python
{
    "bank_row_index":     int,   # Índice en bank_df
    "jde_row_index":      int,   # Índice en jde_df
    "amount_difference":  float, # bank_abs_amount - jde_abs_amount
}
```

#### Estructura de un match agrupado

```python
{
    "group_id":           int,        # ID único del grupo
    "bank_row_index":     int,        # Índice del movimiento bancario
    "jde_row_indices":    list[int],  # Índices de los movimientos JDE del grupo
    "amount_difference":  float,
}
```

---

### 4.7 `src/matching/exact_matcher.py`

**Responsabilidad:** Implementar el algoritmo de matching exacto.

**Algoritmo:**
1. Para cada movimiento bancario no matcheado, busca en JDE no matcheados.
2. Calcula `|bank_abs - jde_abs| <= AMOUNT_TOLERANCE`.
3. Calcula `|bank_date - jde_date| <= DATE_TOLERANCE_DAYS`.
4. Si hay columnas de tienda, verifica compatibilidad de tipo.
5. Selecciona el candidato con menor diferencia de monto.
6. Marca ambos como `is_matched = True`.

---

### 4.8 `src/matching/grouped_matcher.py`

**Responsabilidad:** Proponer agrupaciones de movimientos JDE que sumen el monto de un movimiento bancario.

**Algoritmo (subset sum con límite de tamaño):**
1. Toma los movimientos bancarios no matcheados ordenados por monto descendente.
2. Para cada movimiento bancario, filtra candidatos JDE por ventana de fechas y compatibilidad de tienda.
3. Ejecuta búsqueda de subconjunto con límite `MAX_GROUP_SIZE`.
4. Si encuentra un subconjunto cuya suma difiere en ≤ `AMOUNT_TOLERANCE`, lo registra como propuesta.
5. No marca como matcheado en esta fase (solo propone).

---

### 4.9 `src/reporting/excel_reporter.py`

**Responsabilidad:** Generar reportes Excel y modificar Papeles de Trabajo.

#### `generate(results, output_dir)` — Nuevo reporte

Usa `xlsxwriter` a través de `pd.ExcelWriter`. Escribe 4 hojas:

| Hoja | Método | Contenido |
|---|---|---|
| Resumen | `_write_summary` | Tabla de métricas clave |
| Conciliados | `_write_matches` | Un registro por movimiento JDE matcheado |
| Pendientes Banco | `_write_pending` | Movimientos banco sin match |
| Pendientes JDE | `_write_pending` | Movimientos JDE sin match |

El método `_df_to_sheet` centraliza el renderizado de DataFrames con:
- Formato de encabezado azul
- Filas alternas con fondo claro
- Formato diferenciado para fechas, montos positivos (verde) y negativos (rojo)
- Autofilter en todas las columnas

#### `write_back_conciliados(source_path, reconciled_aux_facts, match_date)` — Write-back

Usa `openpyxl` para modificar el archivo original preservando fórmulas:

1. Abre el workbook con `openpyxl.load_workbook(source_path)`.
2. Localiza la hoja `AUX CONTABLE` (o `Detalle1` como alternativa).
3. Escanea fila por fila buscando el encabezado que contenga `Aux_Fact` e `Importe`.
4. Para cada fila de datos, si el `Aux_Fact` está en `reconciled_aux_facts`, escribe:
   - Columna `CONCILIADO` → `"Sí"`
   - Columna `FECHA CONCILIACION` → `match_date`
5. Retorna el contenido como `bytes` para descarga directa.

---

### 4.10 `main.py` — Orquestador

**Funciones exportadas:**

| Función | Modo | Descripción |
|---|---|---|
| `run_pipeline(bank, jde, output)` | CLI / directo | Pipeline completo sin interacción |
| `run_pipeline_stage1(bank, jde)` | Streamlit | Fase 1: parsing + matching exacto + propuestas |
| `run_pipeline_stage2(result, approved_ids, output)` | Streamlit | Fase 2: confirmar grupos + reporte |

**Función auxiliar `_prepare_dataframes`:**
Compartida por todas las variantes del pipeline. Ejecuta en orden:
1. Detecta y separa archivos REPORTE CAJA de estados de cuenta normales.
2. Parsea todos los archivos.
3. Normaliza bank y JDE.
4. Enriquece bank con REPORTE CAJA si aplica (`_enrich_bank_with_reporte`).
5. Filtra movimientos JDE por cuentas bancarias (matching exacto por sufijo si no hay coincidencia directa).
6. Valida ambos DataFrames con `DataFrameSchemaValidator`.

---

### 4.11 `app.py` — Interfaz Streamlit

**Flujo de la UI:**

```
Sidebar: carga de archivos (bank + jde)
    │
    ▼
Botón "Ejecutar Fase 1"
    └── run_pipeline_stage1() → session_state["stage1_result"]
    │
    ▼
Tabla de agrupaciones propuestas con checkboxes
    │
    ▼
Botón "Confirmar y generar reporte"
    └── run_pipeline_stage2() → session_state["final_result"]
    │
    ▼
Métricas en tarjetas (st.metric)
Tablas: Conciliados / Pendientes Banco / Pendientes JDE
    │
    ▼
Botones de descarga:
    ├── Reporte de conciliación (.xlsx)
    └── Papel de Trabajo actualizado (.xlsx) [si aplica]
```

**Gestión de estado:** Se usa `st.session_state` para conservar resultados entre rerenders de Streamlit.

---

## 5. Flujo de Datos

```
[Archivo banco .xlsx/.csv]          [Archivo JDE .xlsx/.csv]
         │                                    │
         ▼                                    ▼
    BankParser.parse()              JDEParser.parse() / PapelTrabajoParser.parse()
         │                                    │
         ▼                                    ▼
   BankNormalizer.normalize()       JDENormalizer.normalize()
         │                                    │
         └─────────────┬─────────────────────┘
                       ▼
           DataFrameSchemaValidator.validate_*()
                       │
                       ▼
           ReconciliationEngine.reconcile*()
                       │
              ┌────────┴────────┐
              ▼                 ▼
       exact_matches    grouped_matches (propuestos → confirmados)
              │                 │
              └────────┬────────┘
                       ▼
               results dict
                  │          │
                  ▼          ▼
         ExcelReporter    ExcelReporter
          .generate()    .write_back_conciliados()
                  │          │
                  ▼          ▼
         conciliacion_      Papel de Trabajo
         TIMESTAMP.xlsx     actualizado (.xlsx)
```

---

## 6. Decisiones de Diseño

| Decisión | Alternativa considerada | Razón de la elección |
|---|---|---|
| pandas para procesamiento | SQL / lista de dicts | Velocidad de desarrollo, filtros vectorizados, fácil integración con Excel |
| Patrón estrategia en parsers | Un único parser con `if/else` | Extensibilidad: agregar nuevo banco = nueva clase, sin tocar el resto |
| Pipeline en 2 fases | Pipeline único sin revisión | Permite al usuario validar agrupaciones antes de comprometer el resultado |
| openpyxl para write-back | xlsxwriter | openpyxl preserva fórmulas y formatos existentes; xlsxwriter solo crea archivos nuevos |
| Sin base de datos | SQLite / PostgreSQL | Simplicidad de despliegue; el volumen de datos es manejable en memoria |
| Configuración en `settings.py` | Variables de entorno / .env | Acceso directo en código sin dependencias extra; suficiente para un equipo pequeño |

---

## 7. Manejo de Errores

| Capa | Error | Manejo |
|---|---|---|
| Parsers | Archivo no encontrado | `FileNotFoundError` → CLI termina con `sys.exit(1)` |
| Parsers | Formato no reconocido | `ValueError` con mensaje descriptivo |
| Validator | Schema incompleto o tipos incorrectos | `SchemaValidationError` → se propaga hasta CLI/UI y se muestra al usuario |
| Engine | Sin matches | No es error; pendientes reflejan los movimientos sin conciliar |
| Reporter | Hoja AUX CONTABLE no encontrada | `ValueError` con mensaje descriptivo |
| Todos | Error inesperado | `logger.exception()` + en CLI: `sys.exit(1)` |

---

## 8. Configuración y Extensibilidad

### Agregar soporte para un nuevo banco

1. Crear clase `_NuevoBancoParser(_BaseBankParser)` en `bank_parser.py`.
2. Implementar `parse_raw(raw_df)` que retorne el DataFrame crudo normalizable.
3. Registrar en `BankParser._PARSERS`.

### Ajustar tolerancias

Editar `config/settings.py`:
```python
AMOUNT_TOLERANCE = 0.05    # Más estricto
DATE_TOLERANCE_DAYS = 3    # Más permisivo
MAX_GROUP_SIZE = 5          # Grupos más pequeños
```

### Agregar nueva tienda

Agregar entrada en `TIENDA_ABBREV` en `config/settings.py`:
```python
"NOMBRE COMPLETO": "ABR",
```
