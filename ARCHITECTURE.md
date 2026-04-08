# Guía Completa de Arquitectura - Aplicación de Conciliación Bancaria

Estado del documento: actualizado a cambios de abril 2026.

## 🎯 Objetivo General

La app compara **movimientos bancarios** (estado de cuenta) contra **registros JDE** (sistema contable) para identificar cuáles están conciliados, cuáles no, y por qué cantidad coinciden.

**Entrada:** 2 archivos Excel (banco + JDE)  
**Salida:** Reporte Excel con matches exactos, agrupados y pendientes

---

## 🏗️ Arquitectura en 4 Capas

```
┌─────────────────────────────────────────┐
│  PRESENTACIÓN (app.py — Streamlit UI)   │ ← Usuario carga archivos
├─────────────────────────────────────────┤
│  ORQUESTACIÓN (main.py)                 │ ← Coordina el flujo
├─────────────────────────────────────────┤
│  LÓGICA (parsers, normalizers, engine)  │ ← Procesa y concilia
├─────────────────────────────────────────┤
│  DATOS (archivos Excel)                 │ ← Fuente de verdad
└─────────────────────────────────────────┘
```

---

## 🔄 Flujo de Datos Principal (La Ruta Crítica)

### **ETAPA 1: CARGA Y PREPARACIÓN**

```
┌─ app.py ────────────────┐
│ Usuario sube archivos   │
└───────────┬─────────────┘
            ↓
┌─ main.py._prepare_dataframes() ───────────────────────────────┐
│ 1. Parse banco (BankParser)                                    │
│    └─→ Detecta tipo: BBVA, Scotiabank, Mercado Pago, etc     │
│ 2. Parse JDE (JDEParser)                                       │
│    └─→ Si es Excel → PapelTrabajoParser (con Aux_Fact)       │
│ 3. Normalizar (BankNormalizer, JDENormalizer)                 │
│    └─→ Estandariza columnas: movement_date, amount_signed, etc│
│ 4. Validar schema (SchemaValidator)                           │
│    └─→ Verifica que tenga todas las columnas requeridas      │
│ 5. Enriquecer banco con REPORTE_CAJA (si existe)             │
│    └─→ Agrega tienda + tipo de pago al banco                │
│ 6. Filtrar por cuenta bancaria                                │
│    └─→ JDE debe coincidir con cuenta del banco              │
└────────────────────────────────────────────────────────────────┘
            ↓
       DataFrame limpio y validado
```

**Resultado:** `bank_df` y `jde_df` listos, normalizados, con columnas estándar

---

### **ETAPA 2: MOTOR DE CONCILIACIÓN (Stage 1)**

```
┌─ ReconciliationEngine.reconcile_interactive() ──────────────┐
│                                                              │
│ PASO 1: MATCHING EXACTO                                     │
│ ────────────────────────                                    │
│ Para cada movimiento bancario:                              │
│   1. Buscar en JDE con monto EXACTO + fecha (±2 días)      │
│   2. FILTRAR por tienda/tipo con reglas estrictas          │
│   3. FILTRAR por tipo de movimiento (comisión/no-comisión) │
│   4. Filtrar por compatibilidad de cuenta (incluye sufijo) │
│   5. Resolver unicidad priorizando bancos con menos        │
│      candidatos exactos (evita pendientes falsos)          │
│ Resultado: lista de exact_matches                          │
│                                                              │
│ PASO 2: MATCHING AGRUPADO (Propuestas)                     │
│ ────────────────────────                                    │
│ Para movimientos SIN match exacto:                         │
│   1. Agrupar JDE: busca N movimientos que sumen            │
│      el monto bancario (subset sum problem)                 │
│   2. Permite hasta 10 movimientos por grupo                │
│   3. Filtra por tienda (si existe)                         │
│   4. Regla de negocio: CARGO POR DISPERSION solo agrupa    │
│      contra JDE NOMINA (sin completar con comisiones)      │
│   5. Resultado: grouped_match (1 banco ← N JDE)            │
│                                                              │
│ PASO 3: MATCHING INVERSO (Reverso)                         │
│ ────────────────────────                                    │
│ Si JDE sin match SIN encontrar agrupación:                │
│   1. Buscar 1 movimiento JDE que sea suma de N bancos      │
│   2. Regla simétrica: JDE NOMINA solo con bancos           │
│      CARGO POR DISPERSION                                  │
│   2. Resultado: reverse_grouped_match (N banco → 1 JDE)   │
└──────────────────────────────────────────────────────────────┘
            ↓
    Propuestas (usuario debe aprobar)
```

**Salida:**
- `exact_matches`: Movimientos que ya son matches 100%
- `proposed_grouped_matches`: Agrupaciones a revisar
- `proposed_reverse_grouped_matches`: Agrupaciones inversas a revisar

---

### **ETAPA 3: VALIDACIÓN POR USUARIO (Stage 2)**

```
┌─ app.py (Streamlit UI) ────────────────────┐
│                                             │
│ Mostrar propuestas al usuario:             │
│ ├─ Check match exacto: ✓ (automático)    │
│ ├─ Checkbox por cada agrupación           │
│ │  "¿Apruebas esta agrupación?"          │
│ └─ Botón: "Confirmar y finalizar"        │
│                                             │
└─────────────────┬───────────────────────────┘
                  ↓
      Usuario selecciona qué aprobar
                  ↓
┌─ main.py.run_pipeline_stage2() ───────────────────┐
│                                                     │
│ engine.confirm_grouped_matches(                   │
│     interactive_result,          # Del stage 1   │
│     approved_group_ids,          # Del usuario   │
│ )                                                 │
│                                                     │
│ → Clasifica como "conciliados":                  │
│   ✓ Exactos (automáticos)                       │
│   ✓ Agrupaciones aprobadas                      │
│                                                     │
│ → Clasifica como "pendientes":                   │
│   ✗ Agrupaciones rechazadas                     │
│   ✗ Movimientos sin match                       │
│                                                     │
└─────────────────┬──────────────────────────────────┘
                  ↓
        Resultado final clasificado
```

---

## 🔍 Componentes Clave

### **1. PARSERS** (`src/parsers/`)

Leen archivos Excel y extraen datos:

```python
BankParser
├─ _BBVAParser        → BBVA tiene formato especial
├─ _ScotiabankParser  → Scotiabank (14 columnas)
├─ _MercadoPagoParser → Mercado Pago + filtro gris
├─ _NetPayParser      → NetPay
└─ _ReporteCajaParser → REPORTE_CAJA (enriquecimiento)

JDEParser
├─ CSVParser          → Cuando es .csv (2 cuentas)
└─ PapelTrabajoParser → Cuando es .xlsx con Aux_Fact
                         (Papel de Trabajo para 6614 y 7133)
```

**Importante:** Los parsers detectan automáticamente qué tipo de archivo es.

**Archivos principales:**
- `bank_parser.py` - Orquesta todos los parsers bancarios
- `jde_parser.py` - Detecta si es CSV o Papel de Trabajo
- `conciliacion_parser.py` - Lee historiales de conciliación

---

### **2. NORMALIZERS** (`src/normalizers/`)

Estandarizan columnas a un esquema común:

**Entrada:** Columnas variadas (cada banco tiene nombres diferentes)  
**Salida:** Columnas estándar

```python
Columnas estándar:
├─ account_id        → Cuenta bancaria
├─ movement_date     → Fecha (Python datetime)
├─ description       → Concepto
├─ amount_signed     → Monto con signo (+/-)
├─ abs_amount        → Monto absoluto (|monto|)
├─ movement_type     → Tipo (DEBIT, CREDIT, FEE, etc)
├─ source            → BANK o JDE
├─ tienda            → Tienda (si existe, ej: "OUG", "FAB")
└─ tipo_jde          → Tipo JDE (si existe)
```

**Archivos principales:**
- `bank_normalizer.py` - Normaliza movimientos bancarios
- `jde_normalizer.py` - Normaliza movimientos JDE

Cambios recientes:
- Si un monto llega en columna de retiro con signo positivo, se normaliza como retiro (negativo).
- Si un monto llega en columna de depósito con signo negativo, se respeta como retiro.

---

### **3. VALIDADORES** (`src/validacion/`)

```python
SchemaValidator
├─ Verifica columnas requeridas
├─ Verifica tipos de datos
└─ Rechaza DataFrames inválidos
```

---

### **4. ENGINE** (`src/matching/reconciliation_engine.py`)

**El corazón del sistema.** Implementa 3 estrategias:

#### **a) Matching Exacto**

```python
def _find_exact_match(bank_row, jde_candidates):
    """Busca 1 match JDE con monto EXACTO ± 0.50"""

    # 1. Filtrar por fecha (±2 días)
    date_range = jde_candidates[
        (jde_candidates['movement_date'] >= bank_date - 2days) &
        (jde_candidates['movement_date'] <= bank_date + 2days)
    ]

    # 2. Filtrar por tienda (si banco tiene tienda)
    if bank_tienda:
        date_range = date_range[
            date_range['tienda'].isna() |  # JDE sin tienda (acepta todos)
            (date_range['tienda'] == bank_tienda)  # O tienda coincide
        ]

    # 3. Filtrar por tipo (comisión/no-comisión)
    # Si banco es comisión → solo candidatos JDE con comisión

    # 4. Buscar monto exacto
    return date_range[date_range['abs_amount'] == bank_amount]
```

**Flujo:**
1. Toma un movimiento bancario
2. Busca JDE's con monto exacto (±0.50 centavos)
3. Filtra por fecha (±2 días)
4. Filtra por tienda si ambos tienen
5. Filtra por cuenta compatible (incluye equivalencia por sufijo y cuentas como texto numérico con `.0`)
6. Resuelve conflictos de unicidad priorizando movimientos banco con menos candidatos
7. Si encuentra 1 disponible → es un exact_match

#### **b) Matching Agrupado (Subset Sum)**

```
Problema: Dado monto banco = 1000, encontrar N movimientos JDE que sumen 1000

Ejemplo:
    Banco: movimiento por 1000
    JDE: 300 + 400 + 300 = 1000  ✓ Match!

Algoritmo: Backtracking con poda
    - Ordena JDE por monto (menor primero)
    - Prueba combinaciones recursivas
    - Detiene si suma > monto objetivo
    - Máximo de combinaciones por grupo: 10
```

**Diferenciación por tienda:**
- Si banco tiene tienda, solo agrupa JDE's de la misma tienda
- Si banco no tiene tienda, agrupa cualquier JDE

#### **c) Matching Inverso (N→1)**

```
Si banco tiene 2 movimientos sin match:
    Banco: 300 + 700 = 1000
    JDE: 1 movimiento de 1000

Búsqueda: ¿Hay 1 JDE cuyo monto es suma de N bancos?
Resultado: reverse_grouped_match (N banco → 1 JDE)
```

---

### **5. REPORTER** (`src/reporting/excel_reporter.py`)

Genera 2 tipos de reportes:

#### **a) Reporte principal (`generate()`)**

```
conciliacion_YYYYMMDD_HHMMSS.xlsx
├─ Resumen              → Métricas totales
├─ Exactos              → 1←→1 matches
├─ Agrupados            → 1←N matches confirmados
├─ Agrupados Inversos   → N←1 matches confirmados
├─ Pendientes Banco     → Movimientos del banco sin match
└─ Pendientes JDE       → Movimientos JDE sin match
```

#### **b) Write-back del Papel de Trabajo (`write_back_conciliados()`)**

```
Toma el Papel de Trabajo original (.xlsx) y:
1. Busca la hoja "AUX CONTABLE"
2. Busca columnas: Aux_Fact, CONCILIADO, FECHA CONCILIACION
3. Para cada Aux_Fact conciliado:
   ├─ Escribe "Sí" en columna CONCILIADO
   └─ Escribe fecha de conciliación
        (fecha más reciente del banco conciliado)
4. Retorna bytes del archivo modificado

Nota: Preserva 100% del formato original
      (colores, filtros, tablas, estilos, etc)
```

---

### **6. UTILIDADES** (`src/utils/`)

```python
logger.py          → Sistema de logging centralizado
amount_utils.py    → Operaciones con montos (redondeo, conversión)
date_utils.py      → Operaciones con fechas
```

---

## 💻 Casos Especiales Implementados

### **1. Cuenta 6614 (BBVA) - Enriquecimiento**

```
Entrada: REPORTE_CAJA
├─ Contiene: tienda + tipo_pago
├─ Se usa para enriquecer los movimientos de 6614
└─ Resultado: banco_df ahora tiene tienda + tipo_pago

Flujo:
    REPORTE_CAJA (tienda, tipo_pago)
           ↓
    Join por (fecha, monto) con banco 6614
           ↓
    banco_df enriquecido con tienda
```

### **2. Mercado Pago - Filtro de Grises**

```
Mercado Pago incluye filas con color gris (header de transacciones):
- Detecta: Color donde R=G=B (gris puro en hex AARRGGBB)
- Acción: Descarta esas filas completamente
- Nivel: Parser (early filtering)

Implementación:
  def _is_color_ignored(self, color):
      """Detecta colores grises: R=G=B"""
      if color is None or len(color) < 6:
          return False
      try:
          r = int(color[2:4], 16)
          g = int(color[4:6], 16)
          b = int(color[6:8], 16)
          return r == g == b  # Gris si componentes iguales
      except (ValueError, IndexError):
          return False
```

### **3. Cuentas 6614 y 7133 - Papel de Trabajo**

```
SOLO estas cuentas usan:
- Archivo JDE: Papel de Trabajo Excel (con Aux_Fact)
- Write-back: Marca movimientos conciliados en el archivo

Cualquier otra cuenta:
- Archivo JDE: CSV normal
- Sin write-back

Configuración: PAPEL_TRABAJO_ACCOUNTS = {"6614", "7133"}
Comparación: Soporta tanto "7133" como "20305077133" (últimos 4 dígitos)
```

### **4. Scotiabank - Validación de Columnas**

```
Scotiabank espera 14 columnas
Si el archivo tiene menos:
    ├─ Detecta dinámicamente
    ├─ Usa Series vacío para columnas faltantes
    └─ No crashea

Implementación:
    if num_cols > self._IDX_DETAIL:
        detail = df.iloc[:, self._IDX_DETAIL].astype(str).str.strip()
    else:
        detail = pd.Series("", index=df.index)
        logger.warning(f"Columna detalle no existe (total={num_cols})")
```

---

## 🎛️ Configuración (`config/settings.py`)

```python
AMOUNT_TOLERANCE = 0.50       # Tolerancia máxima en monto (centavo)
DATE_TOLERANCE_DAYS = 2       # Diferencia máxima de días permitida
MAX_GROUP_SIZE = 10           # Máximo de movimientos por agrupación
ROUND_DECIMALS = 2            # Decimales para redondeo

PAPEL_TRABAJO_ACCOUNTS = {"6614", "7133"}  # Solo estas usan Papel de Trabajo

TIENDA_ABBREV = {             # Mapeo nombre completo → abreviatura JDE
    "FABRICA": "FAB",
    "OUTLET FRESNILLO": "OUF",
    # ... más mappeos
}
```

---

## 🎨 Frontend (Streamlit - `app.py`)

### **Flujo principal:**

```
1. CARGA (file_uploader)
   ↓
2. PROCESSING (spinner)
   ├─ Stage 1: matching exacto + propuestas
   ├─ Guarda metadata (_is_papel_trabajo, _jde_bytes)
   └─ Salta a fase "validating"
   ↓
3. VALIDACIÓN (checkboxes por cada propuesta)
   ├─ Muestra agrupaciones propuestas
   ├─ Usuario decide qué aprobar
   └─ Botón: "Confirmar"
   ↓
4. RESULTADOS
   ├─ Métricas: exactos, agrupados, pendientes
   ├─ Tablas detalladas
   ├─ Descarga reporte Excel
   └─ Si Papel de Trabajo: descarga con Aux_Fact marcados
```

### **Características especiales:**

- **Selector de fecha:** User-selectable para el nombre del archivo descargado
- **Fecha de conciliación automática:** Usa la fecha más reciente del banco
- **Debug panel:** Muestra información interna (opcional, comentado)
- **Metadata preservation:** Mantiene `_is_papel_trabajo`, `_jde_bytes`, `_bank_accounts`
- **Manejo de errores:** Muestra traceback en caso de problemas

---

## 🚀 Ejemplo Práctico Completo

### **Entrada:**

```
Banco Scotiabank (7133):
  20/03/2026  | 1000.00 | Pago tarjeta | TIENDA: OUG
  20/03/2026  | 500.00  | Pago tarjeta | TIENDA: OUG

Papel de Trabajo JDE (cuenta 7133):
  Aux_Fact: 1234 | 1000.00 | OUG | CONCILIADO: (vacío)
  Aux_Fact: 1235 | 500.00  | OUG | CONCILIADO: (vacío)
```

### **Procesamiento:**

```
1. Parsing → Detecta Scotiabank
2. Normalización → Columnas estándar
3. Matching → Score exacto (monto + fecha + tienda)
4. Stage 1 → 2 exactos encontrados ✓
5. Usuario confirma
6. Stage 2 → Clasifica como "conciliados"
7. Write-back → Marca:
   - Aux_Fact 1234: SÍ | 20/03/2026
   - Aux_Fact 1235: SÍ | 20/03/2026
```

### **Salida:**

```
✓ conciliacion_20032026_141523.xlsx
  ├─ Resumen
  ├─ 2 Exactos
  ├─ 0 Agrupados
  └─ 0 Pendientes

✓ PAPEL DE TRABAJO TRAJETAS 23-03-2026.xlsx (actualizado)
  └─ Ambos Aux_Facts marcados como conciliados
```

---

## 📊 Estrategia de Matching - Árbol de Decisión

```
¿Monto EXACTO en JDE?
├─ SÍ: ¿Fecha coincide (±2 días)?
│   ├─ SÍ: ¿Tienda coincide o alguno sin tienda?
│   │   ├─ SÍ: ¿Tipo de movimiento coincide?
│   │   │   ├─ SÍ: EXACT_MATCH ✓
│   │   │   └─ NO: seguir buscando
│   │   └─ NO: seguir buscando
│   └─ NO: seguir buscando
│
├─ NO: ¿Hay N JDE's que sumen el monto banco?
│   ├─ SÍ: ¿Tienda coincide o alguno sin tienda?
│   │   ├─ SÍ: GROUPED_MATCH (propuesta)
│   │   └─ NO: seguir buscando
│   └─ NO: PENDIENTE BANCO
│
└─ ¿Hay 1 JDE que sea suma de N bancos?
    ├─ SÍ: REVERSE_GROUPED_MATCH (propuesta)
    └─ NO: PENDIENTE BANCO
```

---

## 🔐 Validaciones Implementadas

```python
1. Schema Validation
   └─ Columnas requeridas presentes
   └─ Tipos de datos correctos

2. Date Validation
   └─ Rango de fechas razonable
   └─ Formato consistente

3. Amount Validation
   └─ Montos positivos o negativos válidos
   └─ Tolerancia respetada (±0.50)

4. Account Matching
   └─ Cuenta bancaria = Cuenta JDE
   └─ Soporta prefijos (ej: "20305077133" → "7133")

5. Tienda Consistency
   └─ Si banco tiene tienda, JDE debe coincidir
   └─ Si JDE sin tienda, acepta cualquier banco
```

---

## 📈 Mejoras Futuras Potenciales

1. **Matching inteligente por descripción:** Usar similitud de texto (fuzzy matching)
2. **Machine Learning:** Entrenar modelo para predecir matches correctos
3. **API REST:** Exponer funcionalidad vía endpoints HTTP
4. **Base de datos:** Almacenar histórico de conciliaciones
5. **Reconciliación histórica:** Comparar contra conciliaciones previas
6. **Multi-moneda:** Soportar conversión de tipos de cambio
7. **Auditoria:** Historial completo de cambios y aprobaciones

---

## 🛠️ Tecnologías Usadas

- **Python 3.14.3** - Lenguaje base
- **Pandas** - Procesamiento de datos
- **Streamlit** - Interfaz web
- **OpenPyXL** - Lectura/escritura de Excel
- **NumPy** - Operaciones numéricas

---

## 📞 Soporte

Consulta los archivos específicos:
- Parsing: `src/parsers/README.md` o directamente los comentarios en el código
- Matching: Lee los docstrings en `src/matching/reconciliation_engine.py`
- Reporting: Documentación en `src/reporting/excel_reporter.py`

---

**Última actualización:** 26 de marzo de 2026  
**Versión:** 1.0.0
