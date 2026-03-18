#!/usr/bin/env python3
"""
Debug detallado de por qué el parser BBVA no extrae el 229
"""

import pandas as pd
from pathlib import Path
from src.utils.date_utils import looks_like_date
from src.utils.logger import get_logger

logger = get_logger(__name__)

def debug_bbva_229_row():
    """Ver la fila del 229 paso a paso en el parser BBVA."""
    
    import os
    import glob
    
    temp_base = Path(os.path.expanduser("~")) / "AppData" / "Local" / "Temp"
    bbva_file = None
    
    for temp_dir in glob.glob(str(temp_base / "tmp*")):
        temp_path = Path(temp_dir)
        bbva_candidates = list(temp_path.glob("*6614*.xlsx"))
        if bbva_candidates:
            bbva_file = str(bbva_candidates[0])
            break
    
    if not bbva_file:
        print("❌ Archivo BBVA no encontrado")
        return
    
    print(f"ANALIZANDO: {Path(bbva_file).name}\n")
    
    # Leer raw
    raw = pd.read_excel(bbva_file, sheet_name=0, header=None, dtype=str).fillna("")
    print(f"Total filas en Excel: {len(raw)}\n")
    
    # Simular el parser BBVA
    header = [str(c).strip() for c in raw.iloc[0]]
    df = raw.iloc[1:].copy()
    df.columns = header
    df = df.reset_index(drop=True)
    
    print("="*70)
    print("PASO 1: RENOMBRAR COLUMNAS")
    print("="*70)
    
    rename_map = {
        "FECHA DE OPERACIÓN":     "raw_date",
        "DESCRIPCIÓN":            "description",
        "DESCRIPCIÓN DETALLADA":  "description_detail",
        "DEPÓSITOS":              "raw_deposit",
        "RETIROS":                "raw_withdrawal",
    }
    
    df = df.rename(columns=rename_map)
    print(f"Columnas después rename: {df.columns.tolist()}\n")
    
    # Buscar las filas con 229
    print("="*70)
    print("BÚSQUEDA DE FILAS CON 229")
    print("="*70)
    
    # Buscar en raw_deposit
    mask_229_deposit = df["raw_deposit"].astype(str).str.contains("229", case=False, na=False)
    print(f"Filas con '229' en raw_deposit: {mask_229_deposit.sum()}")
    
    if mask_229_deposit.any():
        for idx in df[mask_229_deposit].index:
            row = df.iloc[idx]
            print(f"\nFila {idx}:")
            print(f"  raw_date: {row['raw_date']!r}")
            print(f"  description: {row['description']!r}")
            print(f"  raw_deposit: {row['raw_deposit']!r}")
            print(f"  raw_withdrawal: {row['raw_withdrawal']!r}")
            print(f"  description_detail: {row['description_detail']!r}")
            
            # Verificar filtro de fecha
            fecha_valid = looks_like_date(row['raw_date'])
            print(f"  looks_like_date(raw_date): {fecha_valid}")
    
    # PASO 2: Aplicar filtro de fecha (como hace el parser BBVA)
    print("\n" + "="*70)
    print("PASO 2: FILTRO DE FECHA")
    print("="*70)
    
    before_filter = len(df)
    df = df[df["raw_date"].apply(looks_like_date)].copy()
    after_filter = len(df)
    
    print(f"Filas antes del filtro: {before_filter}")
    print(f"Filas después del filtro: {after_filter}")
    print(f"Descartadas: {before_filter - after_filter}\n")
    
    # Buscar 229 después del filtro
    mask_229_after = df["raw_deposit"].astype(str).str.contains("229", case=False, na=False)
    print(f"✓ Filas con 229 DESPUÉS del filtro: {mask_229_after.sum()}")
    
    if mask_229_after.any():
        print("\nEncontrado! Detalle:")
        for idx in df[mask_229_after].index:
            row = df.iloc[idx]
            print(f"\nFila {idx}:")
            print(f"  raw_date: {row['raw_date']!r}")
            print(f"  raw_deposit: {row['raw_deposit']!r}")
            print(f"  description: {row['description'][:50]!r}")
    else:
        print("❌ El 229 fue descartado en el filtro de fecha")

if __name__ == "__main__":
    debug_bbva_229_row()
