AMOUNT_TOLERANCE = 0.50       # centavo máximo permitido (BBVA redondea diferente al JDE)
DATE_TOLERANCE_DAYS = 2       # cubre viernes → lunes y fines de semana largos
MAX_GROUP_SIZE = 10           # más entradas por grupo (el filtro por tienda reduce candidatos)
ROUND_DECIMALS = 2

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
    "OUTLET OJOCALIENTE":  "OUO",
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
    "OUO":  "OUO", "OUT": "RG",  "BLVD": "BLVD", "OUZ": "OUZ",
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
    # Mercado Pago: columna Sucursal → abreviatura JDE
    # Outlets (nombres completos y abreviados como vienen en MP)
    "OUTLET CALERA":       "OUC",
    "OUTLET FLLO":         "OUF",
    "OUTLET FRESNILLO":    "OUF",
    "OUTLET GPE":          "OUG",
    "OUTLET GUADALUPE":    "OUG",
    "OUTLET JALPA":        "JAL",
    "OUTLET JEREZ":        "OUJ",
    "OUTLET OJOCALIENTE":  "OUO",
    "OUTLET RIO GRANDE":   "RG",
    "OUTLET ZAC":          "OUZ",
    "OUTLET ZACATECAS":    "OUZ",
    # Tiendas (nombres completos y abreviados como vienen en MP)
    "TIENDA BLVD":         "BLVD",
    "TIENDA BOULEVARD":    "BLVD",
    "TIENDA CALERA":       "OUC",
    "TIENDA FAB":          "FAB",
    "TIENDA FABRICA":      "FAB",
    "TIENDA FLLO":         "FRE",
    "TIENDA FRESNILLO":    "FRE",
    "TIENDA GALERIAS":     "GAL",
    "TIENDA JEREZ":        "JER",
    "TIENDA JALPA":        "JAL",
}