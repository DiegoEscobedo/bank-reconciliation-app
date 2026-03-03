AMOUNT_TOLERANCE = 0.10       # centavo máximo permitido (BBVA redondea diferente al JDE)
DATE_TOLERANCE_DAYS = 1
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
    "O CALERA":            "OUO",   # alias usado en papel de trabajo
    "OUTLET RIO GRANDE":   "OUT",
    "O RIO GRANDE":        "OUT",
    "BOULEVARD":           "BLVD",
    "OUTLET ZACATECAS":    "OUZ",
    "TIENDA FRESNILLO":    "FRE",
    "TIENDA JEREZ":        "JER",
    "OUTLET JALPA":        "JAL",
    "GALERIAS":            "GAL",
    "OUTLET CENTRO":       "OUC",
    "RIO GRANDE":          "RG",
    # Abreviaturas directas (si el archivo ya trae la abreviatura)
    "FAB":  "FAB", "OUF": "OUF", "OUG": "OUG", "OUJ": "OUJ",
    "OUO":  "OUO", "OUT": "OUT", "BLVD": "BLVD", "OUZ": "OUZ",
    "FRE":  "FRE", "JER": "JER", "JAL": "JAL",  "GAL": "GAL",
    "OUC":  "OUC", "RG":  "RG",
}