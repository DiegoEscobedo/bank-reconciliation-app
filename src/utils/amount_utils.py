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
        Formato EUA:        '$4,156.11'     → 4156.11 (coma=miles, punto=decimal)
        Formato México:     '1.234,56'      → 1234.56 (punto=miles, coma=decimal)
        Formato simple:     ' 100,000.00 '  → 100000.00
        Negativo:           '-5,552.96'     → -5552.96
        Especiales:         '-' / '' / NaN  → 0.0
    
    Detecta si el decimal es coma o punto según el contexto:
        - Última separador con exactamente 2 dígitos después = DECIMAL
        - Última separador con 3+ dígitos = SEPARADOR DE MILES (ignorar)
        - Si múltiples separadores idénticos = es el separador de miles
    """
    if pd.isna(value):
        return 0.0

    s = str(value).strip()

    if s in ("", "-", "—", "nan", "None"):
        return 0.0

    # Eliminar símbolo de pesos y espacios
    s = _CURRENCY_RE.sub("", s)

    if s in ("", "-"):
        return 0.0

    # ── Detectar separador decimal automáticamente ────────────────────────
    # Estrategia: Buscar el patrón de dígitos después del último separador
    
    has_comma = "," in s
    has_period = "." in s

    if has_comma and has_period:
        # Tiene ambos → el que esté ÚLTIMO es el decimal
        last_comma_pos = s.rfind(",")
        last_period_pos = s.rfind(".")
        
        if last_period_pos > last_comma_pos:
            # Formato USA: "4,156.11" (últimp separador es el punto)
            # Reemplazar comas (miles) con nada, punto (decimal) con punto
            s = s.replace(",", "")
        else:
            # Formato México: "1.234,56" (último separador es la coma)
            # Reemplazar punto (miles) con nada, coma (decimal) con punto
            s = s.replace(".", "").replace(",", ".")
    elif has_comma and not has_period:
        # Solo comas: ¿es miles o decimal?
        # Contar dígitos después de la última coma
        last_comma_count = len(s.split(",")[-1])
        if last_comma_count == 2:
            # Exactamente 2 dígitos después: es DECIMAL (229,00)
            s = s.replace(",", ".")
        else:
            # 3+ dígitos o 1: es separador de miles (1,000,000)
            s = s.replace(",", "")
    elif has_period and not has_comma:
        # Solo punto: ¿es miles o decimal?
        # Contar dígitos después del último punto
        last_period_count = len(s.split(".")[-1])
        if last_period_count == 2:
            # Exactamente 2 dígitos: probablemente es DECIMAL (229.00)
            # Mantener como está
            pass
        else:
            # 3 dígitos: probablemente es miles (1.000)
            # No hacer nada particular, ya que float() lo manejará
            pass

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
