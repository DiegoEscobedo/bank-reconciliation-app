"""
Utilidades de parseo y manipulación de fechas.
"""

import re
from datetime import datetime

import pandas as pd

# Formatos soportados (en orden de intento)
_KNOWN_FORMATS = [
    "%d/%m/%Y",   # 19/02/2026  ← formato principal (banco y JDE)
    "%Y-%m-%d",   # 2026-02-19
    "%d-%m-%Y",   # 19-02-2026
    "%m/%d/%Y",   # 02/19/2026
    "%d/%m/%y",   # 19/02/26
]

# Acepta DD/MM/YYYY   → 24/02/2026
#          YYYY-MM-DD  → 2026-02-24  (Excel)
#          YYYY-MM-DD HH:MM:SS → 2026-02-24 00:00:00 (Excel con hora)
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})|(\d{4}-\d{2}-\d{2})")

# Meses en español para fechas de Mercado Pago: "18 feb 19:14 hs"
_MESES_ES = {
    'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
}
_MP_DATE_RE = re.compile(r"(\d{1,2})\s+([a-zA-Z]{3})\s*(\d{2}:\d{2})?")


def parse_date_spanish(value) -> pd.Timestamp:
    """
    Parsea fechas en español tipo Mercado Pago: '18 feb 19:14 hs'.
    Usa el año en curso. Retorna pd.NaT si no puede parsear.
    """
    if pd.isna(value):
        return pd.NaT
    s = str(value).strip()
    m = _MP_DATE_RE.match(s)
    if not m:
        return pd.NaT
    day = int(m.group(1))
    mes_str = m.group(2).lower()[:3]
    month = _MESES_ES.get(mes_str)
    if not month:
        return pd.NaT
    year = datetime.now().year
    try:
        return pd.Timestamp(year, month, day)
    except Exception:
        return pd.NaT


def parse_date(value) -> pd.Timestamp:
    """
    Convierte un valor a pd.Timestamp.

    Acepta strings en múltiples formatos (DD/MM/YYYY prioritario).
    Retorna pd.NaT si el valor está vacío o no puede parsearse.
    """
    if pd.isna(value):
        return pd.NaT

    s = str(value).strip()

    if s in ("", "nan", "NaT", "None"):
        return pd.NaT

    for fmt in _KNOWN_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue

    # Último intento con pandas (más flexible)
    try:
        # Si parece YYYY-MM-DD no usar dayfirst para evitar warning
        dayfirst = not bool(re.match(r"\d{4}-\d{2}-\d{2}", s))
        return pd.Timestamp(pd.to_datetime(s, dayfirst=dayfirst))
    except Exception:
        return pd.NaT


def parse_date_series(series: pd.Series) -> pd.Series:
    """
    Aplica parse_date a una Serie completa.
    Retorna una Serie de pd.Timestamp (dtype datetime64[ns]).
    """
    return pd.to_datetime(series.apply(parse_date), errors="coerce")


def looks_like_date(value) -> bool:
    """
    Retorna True si el valor parece una fecha.
    Acepta DD/MM/YYYY, YYYY-MM-DD y YYYY-MM-DD HH:MM:SS (Excel).
    Se usa para filtrar filas de datos en parsers.
    """
    if pd.isna(value):
        return False
    return bool(_DATE_RE.search(str(value).strip()))
