"""
Utilidades de limpieza y conversión de montos.
"""

import re

import pandas as pd

# Patrón para eliminar símbolos de moneda y espacios
_CURRENCY_RE = re.compile(r"[$\s]")


def clean_amount(value) -> float:
    """
    Limpia un valor monetario y retorna float.

    Maneja formatos:
        '$4,156.11'     → 4156.11
        ' 100,000.00 '  → 100000.00
        '-5,552.96'     → -5552.96
        '-'             → 0.0
        ''  / NaN       → 0.0
    """
    if pd.isna(value):
        return 0.0

    s = str(value).strip()

    if s in ("", "-", "—", "nan", "None"):
        return 0.0

    # Eliminar símbolo de pesos y espacios
    s = _CURRENCY_RE.sub("", s)

    # Eliminar separadores de miles (comas), preservando el punto decimal
    s = s.replace(",", "")

    if s in ("", "-"):
        return 0.0

    try:
        return float(s)
    except ValueError:
        return 0.0


def clean_amount_series(series: pd.Series) -> pd.Series:
    """
    Aplica clean_amount a una Serie completa.
    Retorna una Serie de float64.
    """
    return series.apply(clean_amount).astype(float)


def is_empty_amount(value) -> bool:
    """
    Retorna True si el valor representa un monto vacío o nulo (ej. '-', '').
    """
    if pd.isna(value):
        return True
    s = str(value).strip()
    return s in ("", "-", "—", "nan", "None")
