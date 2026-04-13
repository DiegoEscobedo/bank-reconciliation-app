AMOUNT_TOLERANCE = 0.50       # centavo máximo permitido (BBVA redondea diferente al JDE)
DATE_TOLERANCE_DAYS = 2       # cubre viernes → lunes y fines de semana largos
MAX_GROUP_SIZE = 10           # más entradas por grupo (el filtro por tienda reduce candidatos)
GROUPED_CANDIDATE_LIMIT = 15  # top N candidatos por monto para subset-sum (menos = más rápido)
ROUND_DECIMALS = 2

# ── Mapeos de tipo de pago (fuente de verdad) ───────────────────────────────
# FORMA DE PAGO del Papel de Trabajo (JDE) → tipo_jde normalizado
FORMA_PAGO_TO_TIPO_JDE: dict[str, str] = {
    "1": "01", "01": "01",
    "3": "03", "03": "03",
    "8": "03", "08": "03",
    "4": "04", "04": "04",
    "28": "28",
}

# tipo_banco (banco/reporte) → tipos_jde compatibles para conciliación
TIPO_BANCO_TO_JDE_COMPAT: dict[str, set[str]] = {
    "TPV": {"28", "04"},
    "TR":  {"03"},
    "03":  {"01", "03"},
    "01":  {"01"},
    "04":  {"04"},
    "28":  {"28"},
}

# ── Cuentas que usan "Papel de Trabajo" Excel + write-back ─────────────────
# Para estas cuentas: se espera un archivo Excel del Papel de Trabajo, y se actualiza al final
# Para otras cuentas: se aceptan archivos CSV normales del JDE, sin write-back
PAPEL_TRABAJO_ACCOUNTS = {"6614", "7133"}

# COD. TRANSAC bancarios considerados comision para sesgo Banorte
# (aplica a cuentas Banorte, p. ej. 3478 y 6614)
COMMISSION_CODES_BANORTE = {"537", "517", "600", "601", "726"}

# Bancos a los que se aplica el sesgo por COD. TRANSAC de comisiones
COMMISSION_CODE_BIAS_BANKS = {"BANORTE"}

# Alias de compatibilidad hacia atras
COMMISSION_CODES_6614 = COMMISSION_CODES_BANORTE

# ── Mapeo nombre completo de tienda → abreviatura JDE ───────────────────────
# Usado por bank_parser (_ReporteCajaParser) y jde_parser (PapelTrabajoParser)
TIENDA_ABBREV: dict[str, str] = {
    # Nombres completos
    "FABRICA":             "FAB",
    "T FABRICA":           "FAB",
    "T. FABRICA":          "FAB",
    "OUTLET FRESNILLO":    "OUF",
    "OUTLET GUADALUPE":    "OUG",
    "OUTLET JEREZ":        "OUJ",
    "OUTLET OJOCALIENTE":  "OUOJO",
    "O OJOCALIENTE":       "OUO",
    "O CALERA":            "OUC",   # alias usado en papel de trabajo
    "OUTLET RIO GRANDE":   "RG",
    "O RIO GRANDE":        "RG",
    "BOULEVARD":           "BLVD",
    "OUTLET ZACATECAS":    "OUZ",
    "TIENDA FRESNILLO":    "FRE",
    "TIENDA JEREZ":        "JER",
    "OUTLET JALPA":        "JAL",
    "GALERIAS":            "GAL",
    "OUTLET CALERA":       "OUC",
    "RIO GRANDE":          "RG",
    "TIENDA RIO GRANDE":   "RG",
    # Abreviaturas directas (si el archivo ya trae la abreviatura)
    "FAB":  "FAB", "OUF": "OUF", "OUG": "OUG", "OUJ": "OUJ",
    "OUOJO":  "OUOJO", "OUT": "RG",  "BLVD": "BLVD", "OUZ": "OUZ",
    "FRE":  "FRE", "JER": "JER", "JAL": "JAL",  "GAL": "GAL",
    "OUC":  "OUC", "RG":  "RG",
    # NetPay: columna Sucursal → abreviatura JDE
    "CESANTONI":           "FAB",
    "CESANTONI ABASTOS":   "OUZ",
    "CESANTONI BLVD":      "BLVD",
    "CESANTONI BLVD 1":    "BLVD",
    "CESANTONI GUADALUPE": "OUG",
    "CESANTONI FLLO":      "FRE",
    "CESANTONI FRESNILLO": "FRE",
    "CESANTONI OUTLET FRESNILLO": "OUF",
    "CESANTONI JALPA":     "JAL",
    "CESANTONI JEREZ":     "JER",
    "CESANTONI OJOCALIENTE": "OUOJO",
    "CESANTONI RIO GRANDE":   "RG",
    "CESANTONI ZACATECAS":   "OUZ",
    "CESANTONI ZAC":          "OUZ",
    "CESANTONI GALERIAS":   "GAL",
    "CESANTONI GALERIAS 1": "GAL",
    # Mercado Pago: columna Sucursal → abreviatura JDE
    # Outlets (nombres completos y abreviados como vienen en MP)
    "OUTLET CALERA":       "OUC",
    "OUTLET FLLO":         "OUF",
    "OUTLET FRESNILLO":    "OUF",
    "OUTLET GPE":          "OUG",
    "OUTLET GUADALUPE":    "OUG",
    "OUTLET JALPA":        "JAL",
    "OUTLET JEREZ":        "OUJ",
    "OUTLET OJOCALIENTE":  "OUOJO",
    "OUTLET RIO GRANDE":   "RG",
    "OUTLET ZAC":          "OUZ",
    "OUTLET ZACATECAS":    "OUZ",
    # Tiendas (nombres completos y abreviados como vienen en MP)
    "TIENDA BLVD":         "BLVD",
    "TIENDA BOULEVARD":    "BLVD",
    "TIENDA CALERA":       "FAB",
    "TIENDA FAB":          "FAB",
    "TIENDA FABRICA":      "FAB",
    "TIENDA FLLO":         "FRE",
    "TIENDA FRESNILLO":    "FRE",
    "TIENDA GALERIAS":     "GAL",
    "TIENDA JEREZ":        "JER",
    "TIENDA JALPA":        "JAL",
}